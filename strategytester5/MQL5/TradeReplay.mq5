//+------------------------------------------------------------------+
//|                                                 TradeReplay.mq5  |
//|  Visual trade replay for StrategyTester5 backtest results.       |
//|                                                                  |
//|  Reads a replay CSV produced by strategytester5 (exported into   |
//|  MQL5/Files) and redraws the trades on the current chart step    |
//|  by step: entry and exit arrows, an entry-to-exit trend line,    |
//|  stop-loss / take-profit levels and a profit label per trade.    |
//|                                                                  |
//|  Usage: open the chart of the traded symbol, attach this script, |
//|  and set InpFileName to the exported st5_replay_<bot>.csv name.  |
//+------------------------------------------------------------------+
#property copyright "StrategyTester5 contributors"
#property link      "https://github.com/hangyejiadao/StrategyTester5"
#property version   "1.00"
#property script_show_inputs
#property strict

input string InpFileName         = "st5_replay_strategy.csv"; // Replay CSV file (in MQL5/Files)
input int    InpStepMilliseconds = 700;                       // Delay between trade events
input bool   InpShowLevels       = true;                      // Draw SL/TP levels
input bool   InpDeleteOnFinish   = false;                     // Remove drawn objects when done

struct ReplayEvent
{
   datetime time;
   string   symbol;
   string   kind;        // "open" or "close"
   string   direction;   // "long" or "short"
   double   price;
   double   volume;
   double   sl;
   double   tp;
   double   profit;
   long     position_id;
};

struct OpenTrade
{
   long     position_id;
   datetime open_time;
   double   open_price;
   double   sl;
   double   tp;
   string   direction;
};

//--- object name prefix for everything this script draws
const string PREFIX = "ST5REPLAY_";

//+------------------------------------------------------------------+
//| Load replay events from the CSV file                             |
//+------------------------------------------------------------------+
int LoadEvents(ReplayEvent &events[])
{
   int handle = FileOpen(InpFileName, FILE_READ | FILE_CSV | FILE_ANSI, ',');
   if(handle == INVALID_HANDLE)
   {
      PrintFormat("TradeReplay: cannot open %s (error %d). Export a backtest first.", InpFileName, GetLastError());
      return 0;
   }

   // skip the header line
   if(!FileIsEnding(handle))
      FileReadLine(handle);

   int count = 0;
   while(!FileIsEnding(handle))
   {
      string line = FileReadLine(handle);
      if(StringLen(line) == 0)
         continue;

      string parts[];
      if(StringSplit(line, ',', parts) < 10)
         continue;

      ArrayResize(events, count + 1);
      events[count].time        = (datetime)StringToInteger(parts[0]);
      events[count].symbol      = parts[1];
      events[count].kind        = parts[2];
      events[count].direction   = parts[3];
      events[count].price       = StringToDouble(parts[4]);
      events[count].volume      = StringToDouble(parts[5]);
      events[count].sl          = StringToDouble(parts[6]);
      events[count].tp          = StringToDouble(parts[7]);
      events[count].profit      = StringToDouble(parts[8]);
      events[count].position_id = StringToInteger(parts[9]);
      count++;
   }

   FileClose(handle);
   return count;
}

//+------------------------------------------------------------------+
//| Draw an arrow object                                             |
//+------------------------------------------------------------------+
void DrawArrow(const string name, const datetime when, const double price,
               const int arrow_code, const color clr, const string tooltip)
{
   if(!ObjectCreate(0, name, OBJ_ARROW, 0, when, price))
      return;
   ObjectSetInteger(0, name, OBJPROP_ARROWCODE, arrow_code);
   ObjectSetInteger(0, name, OBJPROP_COLOR, clr);
   ObjectSetInteger(0, name, OBJPROP_WIDTH, 2);
   ObjectSetString(0, name, OBJPROP_TOOLTIP, tooltip);
}

//+------------------------------------------------------------------+
//| Draw a dashed level segment (used for SL/TP)                     |
//+------------------------------------------------------------------+
void DrawLevel(const string name, const datetime from_time, const datetime to_time,
               const double price, const color clr)
{
   if(price <= 0)
      return;
   if(!ObjectCreate(0, name, OBJ_TREND, 0, from_time, price, to_time, price))
      return;
   ObjectSetInteger(0, name, OBJPROP_COLOR, clr);
   ObjectSetInteger(0, name, OBJPROP_STYLE, STYLE_DASH);
   ObjectSetInteger(0, name, OBJPROP_RAY_RIGHT, false);
   ObjectSetInteger(0, name, OBJPROP_SELECTABLE, false);
}

//+------------------------------------------------------------------+
//| Script entry point                                               |
//+------------------------------------------------------------------+
void OnStart()
{
   ReplayEvent events[];
   int total = LoadEvents(events);
   if(total == 0)
   {
      Print("TradeReplay: no events to replay.");
      return;
   }

   PrintFormat("TradeReplay: replaying %d events from %s", total, InpFileName);

   OpenTrade opens[];
   datetime last_time = 0;

   for(int i = 0; i < total; i++)
   {
      ReplayEvent ev = events[i];

      // the script draws on the current chart; events of other symbols are skipped
      if(ev.symbol != _Symbol)
         continue;

      string base = PREFIX + IntegerToString(ev.position_id);

      if(ev.kind == "open")
      {
         bool is_long = (ev.direction == "long");
         DrawArrow(base + "_in", ev.time, ev.price,
                   is_long ? 233 : 234,
                   is_long ? clrSeaGreen : clrTomato,
                   StringFormat("%s %.2f @ %s", ev.direction, ev.volume, DoubleToString(ev.price, _Digits)));

         int slot = ArraySize(opens);
         ArrayResize(opens, slot + 1);
         opens[slot].position_id = ev.position_id;
         opens[slot].open_time   = ev.time;
         opens[slot].open_price  = ev.price;
         opens[slot].sl          = ev.sl;
         opens[slot].tp          = ev.tp;
         opens[slot].direction   = ev.direction;
      }
      else if(ev.kind == "close")
      {
         bool is_long = (ev.direction == "long");
         DrawArrow(base + "_out", ev.time, ev.price,
                   is_long ? 234 : 233,
                   ev.profit >= 0 ? clrSeaGreen : clrTomato,
                   StringFormat("exit @ %s, profit %.2f", DoubleToString(ev.price, _Digits), ev.profit));

         // find the matching open trade
         for(int j = 0; j < ArraySize(opens); j++)
         {
            if(opens[j].position_id != ev.position_id)
               continue;

            string line_name = base + "_line";
            if(ObjectCreate(0, line_name, OBJ_TREND, 0, opens[j].open_time, opens[j].open_price, ev.time, ev.price))
            {
               ObjectSetInteger(0, line_name, OBJPROP_COLOR, ev.profit >= 0 ? clrSeaGreen : clrTomato);
               ObjectSetInteger(0, line_name, OBJPROP_WIDTH, 2);
               ObjectSetInteger(0, line_name, OBJPROP_RAY_RIGHT, false);
            }

            if(InpShowLevels)
            {
               DrawLevel(base + "_sl", opens[j].open_time, ev.time, opens[j].sl, clrTomato);
               DrawLevel(base + "_tp", opens[j].open_time, ev.time, opens[j].tp, clrSeaGreen);
            }

            // profit label near the middle of the trade
            datetime mid_time = opens[j].open_time + (datetime)((ev.time - opens[j].open_time) / 2);
            double   mid_price = (opens[j].open_price + ev.price) / 2.0;
            string label_name = base + "_label";
            if(ObjectCreate(0, label_name, OBJ_TEXT, 0, mid_time, mid_price))
            {
               ObjectSetString(0, label_name, OBJPROP_TEXT,
                               StringFormat("%s %.2f", ev.profit >= 0 ? "+" : "", ev.profit));
               ObjectSetInteger(0, label_name, OBJPROP_COLOR, ev.profit >= 0 ? clrSeaGreen : clrTomato);
               ObjectSetInteger(0, label_name, OBJPROP_FONTSIZE, 9);
            }
            break;
         }
      }

      last_time = ev.time;
      ChartRedraw(0);
      if(InpStepMilliseconds > 0)
         Sleep(InpStepMilliseconds);
   }

   PrintFormat("TradeReplay: finished at %s", TimeToString(last_time, TIME_DATE | TIME_SECONDS));

   if(InpDeleteOnFinish)
      ObjectsDeleteAll(0, PREFIX);
}
