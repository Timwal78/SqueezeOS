//+------------------------------------------------------------------+
//|                                       FlagPatternDetector.mq5    |
//|               SqueezeOS — Price Action Toolkit (Part 69)         |
//|                         ScriptMasterLabs™ / SqueezeOS            |
//+------------------------------------------------------------------+
//  Implements ATR-normalised pole validation, retracement depth
//  scoring, consolidation-channel constraints, and close-based
//  breakout confirmation for both bull and bear flag formations.
//
//  Algorithm overview
//  ──────────────────
//  1. Pole scan   — find a sharp directional impulse (InpPoleLenMin–
//                   InpPoleLenMax bars) whose height ≥ InpPoleATRMult × ATR.
//  2. Flag scan   — after the pole tip, price must consolidate for
//                   InpConsolMin–InpConsolMax bars inside a channel
//                   whose slope opposes the pole. Retrace depth must
//                   fall inside [InpRetraceMin, InpRetraceMax].
//  3. Breakout    — close (or high/low) crosses the channel boundary
//                   in the direction of the pole by ≥ InpBrkATRMult × ATR.
//  4. Visuals     — pole line, flag channel lines, breakout arrow, and
//                   optional info label drawn as chart objects.
//
//  Live endpoint: https://lively-fascination-production-41fa.up.railway.app
//+------------------------------------------------------------------+
#property copyright   "ScriptMasterLabs™ / SqueezeOS"
#property link        "https://lively-fascination-production-41fa.up.railway.app"
#property version     "1.00"
#property description "Flag Pattern Detector — ATR-normalised pole, Fibonacci retracement, channel breakout."
#property indicator_chart_window
#property indicator_buffers 2
#property indicator_plots   2

// Bull breakout arrow (below bar)
#property indicator_label1  "Bull Flag Break"
#property indicator_type1   DRAW_ARROW
#property indicator_color1  clrLime
#property indicator_style1  STYLE_SOLID
#property indicator_width1  2

// Bear breakout arrow (above bar)
#property indicator_label2  "Bear Flag Break"
#property indicator_type2   DRAW_ARROW
#property indicator_color2  clrRed
#property indicator_style2  STYLE_SOLID
#property indicator_width2  2

//+------------------------------------------------------------------+
//| Inputs                                                            |
//+------------------------------------------------------------------+
input group "──── Pole Detection ────"
input int    InpPoleLenMin   = 5;      // Min pole bars
input int    InpPoleLenMax   = 20;     // Max pole bars
input double InpPoleATRMult  = 1.5;    // Min pole height (ATR multiples)
input int    InpATRPeriod    = 14;     // ATR period

input group "──── Flag Consolidation ────"
input int    InpConsolMin    = 3;      // Min consolidation bars
input int    InpConsolMax    = 20;     // Max consolidation bars
input double InpRetraceMin   = 0.236;  // Retracement floor  (23.6% Fib)
input double InpRetraceMax   = 0.618;  // Retracement ceiling (61.8% Fib)
input double InpSlopeFactor  = 0.5;   // Max channel slope vs ATR/bar

input group "──── Breakout Confirmation ────"
input bool   InpRequireClose = true;   // Require close beyond channel line
input double InpBrkATRMult   = 0.10;   // Min breakout magnitude (ATR multiples)

input group "──── Visuals ────"
input color  InpBullPoleClr  = clrDodgerBlue;  // Bull pole colour
input color  InpBearPoleClr  = clrOrangeRed;   // Bear pole colour
input color  InpFlagClr      = clrGold;        // Flag channel colour
input color  InpBullSigClr   = clrLime;        // Bull breakout label colour
input color  InpBearSigClr   = clrRed;         // Bear breakout label colour
input bool   InpShowLabels   = true;            // Show ATR-ratio / retrace label
input int    InpMaxPatterns  = 50;              // Max patterns rendered at once

//+------------------------------------------------------------------+
//| Indicator buffers                                                  |
//+------------------------------------------------------------------+
double BullBuffer[];
double BearBuffer[];

//+------------------------------------------------------------------+
//| Internal state                                                     |
//+------------------------------------------------------------------+
int    g_atrHandle   = INVALID_HANDLE;
double g_atrBuf[];

// Unique prefix so objects don't collide with other indicators
const string OBJ_PFX = "FPD_";

//+------------------------------------------------------------------+
//| Helpers                                                            |
//+------------------------------------------------------------------+
string ObjName(string tag, int bar) { return OBJ_PFX + tag + "_" + IntegerToString(bar); }

void DeleteObjects()
{
    int total = ObjectsTotal(0, -1, -1);
    for(int i = total - 1; i >= 0; i--)
    {
        string name = ObjectName(0, i, -1, -1);
        if(StringFind(name, OBJ_PFX) == 0)
            ObjectDelete(0, name);
    }
}

// Draw a trend line between two chart bars
void DrawLine(string name, datetime t1, double p1, datetime t2, double p2,
              color clr, int width = 1, ENUM_LINE_STYLE style = STYLE_SOLID)
{
    if(ObjectFind(0, name) >= 0) ObjectDelete(0, name);
    ObjectCreate(0, name, OBJ_TREND, 0, t1, p1, t2, p2);
    ObjectSetInteger(0, name, OBJPROP_COLOR,     clr);
    ObjectSetInteger(0, name, OBJPROP_WIDTH,     width);
    ObjectSetInteger(0, name, OBJPROP_STYLE,     style);
    ObjectSetInteger(0, name, OBJPROP_RAY_RIGHT, false);
    ObjectSetInteger(0, name, OBJPROP_BACK,      true);
}

// Draw a text label at a price/time
void DrawLabel(string name, datetime t, double p, string txt, color clr)
{
    if(!InpShowLabels) return;
    if(ObjectFind(0, name) >= 0) ObjectDelete(0, name);
    ObjectCreate(0, name, OBJ_TEXT, 0, t, p);
    ObjectSetString (0, name, OBJPROP_TEXT,      txt);
    ObjectSetInteger(0, name, OBJPROP_COLOR,     clr);
    ObjectSetInteger(0, name, OBJPROP_FONTSIZE,  8);
    ObjectSetString (0, name, OBJPROP_FONT,      "Courier New");
}

//+------------------------------------------------------------------+
//| Flag-pattern scanner — returns true when a valid pattern ends     |
//| at bar index [breakBar] (0 = current bar, values are in series    |
//| order, i.e. iHigh/iLow/iClose).                                  |
//|                                                                    |
//| Parameters (all bar indices, 0 = current):                        |
//|   breakBar   — candidate breakout bar                             |
//|   isBull     — true=bullish, false=bearish                        |
//| Out parameters:                                                    |
//|   poleStart, poleTip, flagEnd — bar indices of pattern nodes      |
//|   retrace, atrRatio           — metrics for the label             |
//+------------------------------------------------------------------+
bool ScanPattern(int breakBar, bool isBull,
                 int &poleStart, int &poleTip, int &flagEnd,
                 double &retrace, double &atrRatio,
                 double currentATR)
{
    int bars = Bars(_Symbol, PERIOD_CURRENT);

    // ── 1. Try every consolidation length ────────────────────────
    for(int cLen = InpConsolMin; cLen <= InpConsolMax; cLen++)
    {
        flagEnd  = breakBar;
        int tip  = breakBar + cLen;  // pole tip (older bar)

        if(tip >= bars) continue;

        // ── 2. Try every pole length ──────────────────────────────
        for(int pLen = InpPoleLenMin; pLen <= InpPoleLenMax; pLen++)
        {
            int pStart = tip + pLen;
            if(pStart >= bars) continue;

            // Pole base and tip prices
            double pBaseH = iHigh (_Symbol, PERIOD_CURRENT, pStart);
            double pBaseL = iLow  (_Symbol, PERIOD_CURRENT, pStart);
            double pTipH  = iHigh (_Symbol, PERIOD_CURRENT, tip);
            double pTipL  = iLow  (_Symbol, PERIOD_CURRENT, tip);

            double poleHigh = isBull ? pTipH  : pBaseH;
            double poleLow  = isBull ? pBaseL : pTipL;
            double poleH    = poleHigh - poleLow;

            if(poleH <= 0) continue;

            // ATR normalisation check
            atrRatio = poleH / currentATR;
            if(atrRatio < InpPoleATRMult) continue;

            // Verify directional momentum in pole (monotone highs/lows)
            bool poleValid = true;
            for(int k = tip + 1; k <= pStart - 1; k++)
            {
                if(isBull)
                {
                    if(iLow(_Symbol, PERIOD_CURRENT, k) < poleLow)
                    { poleValid = false; break; }
                }
                else
                {
                    if(iHigh(_Symbol, PERIOD_CURRENT, k) > poleHigh)
                    { poleValid = false; break; }
                }
            }
            if(!poleValid) continue;

            // ── 3. Consolidation (flag) channel ───────────────────
            double hiMax = -DBL_MAX, hiMin = DBL_MAX;
            double loMax = -DBL_MAX, loMin = DBL_MAX;

            for(int k = flagEnd; k <= tip; k++)
            {
                double h = iHigh(_Symbol, PERIOD_CURRENT, k);
                double l = iLow (_Symbol, PERIOD_CURRENT, k);
                if(h > hiMax) hiMax = h;
                if(h < hiMin) hiMin = h;
                if(l > loMax) loMax = l;
                if(l < loMin) loMin = l;
            }

            // Retracement depth (measured from pole tip to flag extreme)
            double flagExtreme = isBull ? loMax : hiMin;
            retrace = MathAbs(flagExtreme - (isBull ? poleHigh : poleLow)) / poleH;

            if(retrace < InpRetraceMin || retrace > InpRetraceMax) continue;

            // Channel slope constraint: opposing the pole direction
            // Estimate slope as (newest_high - oldest_high) / cLen bars
            double newestH = iHigh(_Symbol, PERIOD_CURRENT, flagEnd);
            double oldestH = iHigh(_Symbol, PERIOD_CURRENT, tip);
            double slope   = (newestH - oldestH) / (double)cLen / currentATR;

            if(isBull  && slope > InpSlopeFactor) continue;  // must slope down for bull flag
            if(!isBull && slope < -InpSlopeFactor) continue; // must slope up  for bear flag

            // ── 4. Breakout confirmation ──────────────────────────
            // Upper/lower channel boundaries projected to breakBar
            double chanHigh, chanLow;
            {
                double dHi = (newestH - oldestH) / (double)cLen;
                double dLo = (iLow(_Symbol, PERIOD_CURRENT, flagEnd) -
                              iLow(_Symbol, PERIOD_CURRENT, tip)) / (double)cLen;
                chanHigh = newestH + dHi;  // projected one more bar
                chanLow  = iLow(_Symbol, PERIOD_CURRENT, flagEnd) + dLo;
            }

            double brClose = iClose(_Symbol, PERIOD_CURRENT, breakBar);
            double brHigh  = iHigh (_Symbol, PERIOD_CURRENT, breakBar);
            double brLow   = iLow  (_Symbol, PERIOD_CURRENT, breakBar);

            bool broke = false;
            if(isBull)
            {
                double brkLevel = chanHigh;
                bool   overLine = InpRequireClose ? brClose > brkLevel : brHigh > brkLevel;
                broke = overLine && (brClose - brkLevel) >= InpBrkATRMult * currentATR;
            }
            else
            {
                double brkLevel = chanLow;
                bool   overLine = InpRequireClose ? brClose < brkLevel : brLow < brkLevel;
                broke = overLine && (brkLevel - brClose) >= InpBrkATRMult * currentATR;
            }

            if(!broke) continue;

            poleStart = pStart;
            poleTip   = tip;
            return true;
        }
    }
    return false;
}

//+------------------------------------------------------------------+
//| OnInit                                                             |
//+------------------------------------------------------------------+
int OnInit()
{
    g_atrHandle = iATR(_Symbol, PERIOD_CURRENT, InpATRPeriod);
    if(g_atrHandle == INVALID_HANDLE)
    {
        Print("FlagPatternDetector: iATR() failed");
        return INIT_FAILED;
    }

    SetIndexBuffer(0, BullBuffer, INDICATOR_DATA);
    SetIndexBuffer(1, BearBuffer, INDICATOR_DATA);

    PlotIndexSetDouble(0, PLOT_EMPTY_VALUE, 0.0);
    PlotIndexSetDouble(1, PLOT_EMPTY_VALUE, 0.0);

    PlotIndexSetInteger(0, PLOT_ARROW, 233);   // up triangle
    PlotIndexSetInteger(1, PLOT_ARROW, 234);   // down triangle

    IndicatorSetString(INDICATOR_SHORTNAME,
        StringFormat("FlagPattern(pole%d-%d,%.1fATR,F%d-%d,R%.0f-%.0f%%)",
            InpPoleLenMin, InpPoleLenMax, InpPoleATRMult,
            InpConsolMin, InpConsolMax,
            InpRetraceMin * 100, InpRetraceMax * 100));

    ArraySetAsSeries(BullBuffer, true);
    ArraySetAsSeries(BearBuffer, true);
    ArraySetAsSeries(g_atrBuf,   true);

    return INIT_SUCCEEDED;
}

//+------------------------------------------------------------------+
//| OnDeinit — clean up chart objects                                  |
//+------------------------------------------------------------------+
void OnDeinit(const int reason)
{
    if(g_atrHandle != INVALID_HANDLE)
        IndicatorRelease(g_atrHandle);
    DeleteObjects();
    ChartRedraw(0);
}

//+------------------------------------------------------------------+
//| OnCalculate                                                        |
//+------------------------------------------------------------------+
int OnCalculate(const int       rates_total,
                const int       prev_calculated,
                const datetime &time[],
                const double   &open[],
                const double   &high[],
                const double   &low[],
                const double   &close[],
                const long     &tick_volume[],
                const long     &volume[],
                const int      &spread[])
{
    if(rates_total < InpPoleLenMax + InpConsolMax + InpATRPeriod + 5)
        return 0;

    // Copy ATR into series-order buffer
    int copied = CopyBuffer(g_atrHandle, 0, 0, rates_total, g_atrBuf);
    if(copied <= 0) return prev_calculated;

    // On first run scan full history; after that only rescan last bar
    int startBar = (prev_calculated == 0) ? rates_total - 1 : 0;

    // Clear old signals on full recalc
    if(prev_calculated == 0)
    {
        DeleteObjects();
        ArrayInitialize(BullBuffer, 0.0);
        ArrayInitialize(BearBuffer, 0.0);
    }

    // Track how many patterns we've drawn to honour InpMaxPatterns
    int drawnCount = 0;
    if(prev_calculated > 0)
    {
        // Count already-drawn objects
        int total = ObjectsTotal(0, -1, -1);
        for(int i = 0; i < total; i++)
        {
            string name = ObjectName(0, i, -1, -1);
            if(StringFind(name, OBJ_PFX + "POLE") == 0) drawnCount++;
        }
    }

    int minBar = InpPoleLenMax + InpConsolMax + InpATRPeriod + 2;

    for(int bar = startBar; bar >= 1 && drawnCount < InpMaxPatterns; bar--)
    {
        if(bar < minBar || bar >= rates_total) continue;

        double atr = g_atrBuf[bar];
        if(atr <= 0) continue;

        // ── Test bullish flag ──────────────────────────────────────
        int ps, pt, fe;
        double ret, ar;
        if(BullBuffer[bar] == 0.0 &&
           ScanPattern(bar, true, ps, pt, fe, ret, ar, atr))
        {
            BullBuffer[bar] = low[bar] - atr * 0.5;

            // Pole line
            DrawLine(ObjName("POLE_BULL", bar),
                     time[ps], low[ps],
                     time[pt], high[pt],
                     InpBullPoleClr, 2);

            // Flag channel — upper rail
            DrawLine(ObjName("FLAG_HI_BULL", bar),
                     time[pt], high[pt],
                     time[fe], high[fe],
                     InpFlagClr, 1, STYLE_DOT);

            // Flag channel — lower rail
            DrawLine(ObjName("FLAG_LO_BULL", bar),
                     time[pt], low[pt],
                     time[fe], low[fe],
                     InpFlagClr, 1, STYLE_DOT);

            // Info label
            string lbl = StringFormat("BULL FLAG\nPole %.1f ATR\nRetrace %.0f%%",
                                      ar, ret * 100);
            DrawLabel(ObjName("LBL_BULL", bar),
                      time[bar], BullBuffer[bar] - atr * 0.3,
                      lbl, InpBullSigClr);

            drawnCount++;
        }

        // ── Test bearish flag ──────────────────────────────────────
        if(BearBuffer[bar] == 0.0 &&
           ScanPattern(bar, false, ps, pt, fe, ret, ar, atr))
        {
            BearBuffer[bar] = high[bar] + atr * 0.5;

            DrawLine(ObjName("POLE_BEAR", bar),
                     time[ps], high[ps],
                     time[pt], low[pt],
                     InpBearPoleClr, 2);

            DrawLine(ObjName("FLAG_HI_BEAR", bar),
                     time[pt], high[pt],
                     time[fe], high[fe],
                     InpFlagClr, 1, STYLE_DOT);

            DrawLine(ObjName("FLAG_LO_BEAR", bar),
                     time[pt], low[pt],
                     time[fe], low[fe],
                     InpFlagClr, 1, STYLE_DOT);

            string lbl = StringFormat("BEAR FLAG\nPole %.1f ATR\nRetrace %.0f%%",
                                      ar, ret * 100);
            DrawLabel(ObjName("LBL_BEAR", bar),
                      time[bar], BearBuffer[bar] + atr * 0.3,
                      lbl, InpBearSigClr);

            drawnCount++;
        }
    }

    ChartRedraw(0);
    return rates_total;
}
//+------------------------------------------------------------------+
