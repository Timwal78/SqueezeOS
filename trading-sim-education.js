/* ═══════════════════════════════════════════════════════
   ACADEMY — 3-Level Curriculum, Quizzes, Progress Tracking
   ═══════════════════════════════════════════════════════ */

const Academy = (() => {
  let _level    = 'beginner';
  let _lesson   = null;
  let _page     = 0;
  let _quizData = null;
  let _quizIdx  = 0;
  let _quizScore= 0;

  const CURRICULUM = {
    beginner: [
      {
        id:'b1', title:'What is the Stock Market?', time:'5 min', xp:25,
        desc:'Understand what stocks are, how markets work, and why people invest.',
        pages:[
          {title:'What is a Stock?', content:`
            <p class="lesson-text">A <strong>stock</strong> (also called a share or equity) represents ownership in a company. When you buy one share of Apple (AAPL), you own a tiny piece of Apple Inc.</p>
            <div class="lesson-highlight">Companies issue stocks to raise money for growth. Investors buy stocks hoping the company grows and their shares increase in value.</div>
            <p class="lesson-text">The price of a stock is determined by <strong>supply and demand</strong> — how many people want to buy vs. sell at any given moment.</p>
            <div class="lesson-example"><div class="lesson-example-title">Real Example</div><p>If Apple announces a new iPhone and investors are excited, demand for AAPL stock increases, pushing the price up. If earnings disappoint, sellers outnumber buyers and the price falls.</p></div>`
          },
          {title:'How Does the Stock Market Work?', content:`
            <p class="lesson-text">Stock markets are <strong>exchanges</strong> where buyers and sellers trade shares. The biggest US exchanges are:</p>
            <table class="lesson-table"><tr><th>Exchange</th><th>Known For</th><th>Hours</th></tr>
              <tr><td>NYSE</td><td>Largest by market cap, blue-chip stocks</td><td>9:30am - 4:00pm ET</td></tr>
              <tr><td>NASDAQ</td><td>Technology companies, growth stocks</td><td>9:30am - 4:00pm ET</td></tr>
              <tr><td>Options (CBOE)</td><td>Options & derivatives trading</td><td>9:30am - 4:00pm ET</td></tr>
            </table>
            <div class="lesson-tip">💡 <strong>Tip:</strong> Pre-market (4am-9:30am) and after-hours (4pm-8pm) trading also exists but has lower volume and wider spreads.</div>`
          },
          {title:'Types of Stocks', content:`
            <p class="lesson-text">Not all stocks are the same. Key categories:</p>
            <ul class="lesson-list">
              <li><strong>Blue-chip stocks:</strong> Large, established companies (AAPL, MSFT, JPM). Generally more stable.</li>
              <li><strong>Growth stocks:</strong> Companies expected to grow faster than average (NVDA, TSLA). Higher risk/reward.</li>
              <li><strong>Value stocks:</strong> Companies trading below their intrinsic value. Often boring but cheap (PFE, BAC).</li>
              <li><strong>Meme stocks:</strong> Stocks driven by social media hype (AMC, GME). Very volatile, speculative.</li>
              <li><strong>ETFs:</strong> Funds that track an index (SPY tracks S&P 500). Instant diversification.</li>
            </ul>
            <div class="lesson-highlight"><strong>For beginners:</strong> Start with ETFs like SPY or QQQ to get broad market exposure with lower single-stock risk.</div>`
          },
        ],
        quiz:[
          { q:'What does owning a stock mean?', opts:['Lending money to a company','Owning a piece of a company','Earning a fixed salary from a company','Guaranteeing company profits'], ans:1, exp:'A stock represents fractional ownership in a company. As a shareholder, you benefit when the company grows.' },
          { q:'Which exchange is most known for technology stocks?', opts:['NYSE','CBOE','NASDAQ','CME'], ans:2, exp:'NASDAQ is known for listing many major tech companies like Apple, Microsoft, Google, and Amazon.' },
          { q:'What is an ETF?', opts:['A type of bond','A fund that tracks an index','A futures contract','An options strategy'], ans:1, exp:'An ETF (Exchange-Traded Fund) is a collection of securities that typically tracks an index, providing instant diversification.' },
        ]
      },
      {
        id:'b2', title:'Reading Stock Prices & Charts', time:'8 min', xp:30,
        desc:'Learn to read price quotes, understand chart basics, and interpret price action.',
        pages:[
          {title:'Understanding a Stock Quote', content:`
            <p class="lesson-text">When you look up a stock, you see several key data points. Let's break down what each means:</p>
            <table class="lesson-table"><tr><th>Field</th><th>Meaning</th><th>Example</th></tr>
              <tr><td>Last / Price</td><td>Most recent trade price</td><td>$189.50</td></tr>
              <tr><td>Change</td><td>Price change from previous close</td><td>+$2.30</td></tr>
              <tr><td>Change %</td><td>Percentage change from close</td><td>+1.23%</td></tr>
              <tr><td>Open</td><td>First trade price of the day</td><td>$187.20</td></tr>
              <tr><td>High</td><td>Highest price of the day</td><td>$190.80</td></tr>
              <tr><td>Low</td><td>Lowest price of the day</td><td>$186.90</td></tr>
              <tr><td>Volume</td><td>Number of shares traded today</td><td>55M</td></tr>
              <tr><td>Mkt Cap</td><td>Total value of the company</td><td>$2.9T</td></tr>
            </table>`
          },
          {title:'Candlestick Charts Explained', content:`
            <p class="lesson-text">Candlestick charts show price movement over a time period. Each "candle" shows 4 data points: Open, High, Low, Close (OHLC).</p>
            <div class="lesson-highlight">
              🟢 <strong>Green candle:</strong> Close price > Open price (bullish)<br>
              🔴 <strong>Red candle:</strong> Close price < Open price (bearish)
            </div>
            <p class="lesson-text">The body shows the range between open and close. The wicks (thin lines) show the high and low extremes.</p>
            <div class="lesson-example"><div class="lesson-example-title">Reading a Candle</div>
              <p>A tall green candle with small wicks = strong buying pressure, bulls in control.<br>
              A tall red candle with small wicks = strong selling pressure, bears in control.<br>
              A small candle with long wicks = indecision, neither side winning.</p>
            </div>`
          },
          {title:'Key Chart Patterns', content:`
            <p class="lesson-text">Price often forms recognizable patterns that can signal future movement:</p>
            <ul class="lesson-list">
              <li><strong>Uptrend:</strong> Series of higher highs and higher lows — bullish.</li>
              <li><strong>Downtrend:</strong> Series of lower highs and lower lows — bearish.</li>
              <li><strong>Support:</strong> Price level where buyers consistently step in.</li>
              <li><strong>Resistance:</strong> Price level where sellers consistently emerge.</li>
              <li><strong>Breakout:</strong> Price moves decisively through support or resistance.</li>
            </ul>
            <div class="lesson-tip">💡 In SqueezeSim, watch how prices bounce off key levels. The market simulator uses realistic price behavior!</div>`
          },
        ],
        quiz:[
          { q:'A green candlestick means:', opts:['The price went down','The price opened lower and closed higher','The price was unchanged','Trading volume was high'], ans:1, exp:'A green (bullish) candle means the closing price was higher than the opening price — buyers won the day.' },
          { q:'What is "volume" in stock trading?', opts:['The price of a stock','The number of shares traded','The change in price','The market capitalization'], ans:1, exp:'Volume is the number of shares traded during a period. High volume confirms price moves; low volume signals weak moves.' },
          { q:'What is a "support level"?', opts:['A price level where sellers always emerge','A price level where the CEO supports the stock','A price level where buyers consistently step in','The lowest price in history'], ans:2, exp:'Support is a price level where demand is strong enough to prevent the price from falling further. It\'s where buyers historically step in.' },
        ]
      },
      {
        id:'b3', title:'Order Types Explained', time:'7 min', xp:30,
        desc:'Master market orders, limit orders, stop losses, and bracket orders.',
        pages:[
          {title:'Market Orders', content:`
            <p class="lesson-text">A <strong>market order</strong> executes immediately at the best available price. It's the fastest and simplest order type.</p>
            <div class="lesson-highlight"><strong>When to use:</strong> When you need to enter or exit immediately and don't care about exact price. During fast-moving markets or news events.</div>
            <div class="lesson-warning">⚠️ <strong>Slippage risk:</strong> In thin markets, your execution price might be worse than expected. The bid-ask spread widens in volatile conditions.</div>
            <div class="lesson-example"><div class="lesson-example-title">Example</div><p>SPY shows $445.50. You place a market buy order. You might execute at $445.52 due to the spread. Small difference, acceptable in liquid stocks.</p></div>`
          },
          {title:'Limit Orders', content:`
            <p class="lesson-text">A <strong>limit order</strong> only executes at your specified price or better. You control the price but not the timing.</p>
            <div class="lesson-highlight"><strong>Limit Buy:</strong> Executes at or below your limit price.<br><strong>Limit Sell:</strong> Executes at or above your limit price.</div>
            <p class="lesson-text">The order stays open until filled or you cancel it (GTC = Good Till Canceled).</p>
            <div class="lesson-example"><div class="lesson-example-title">Example</div><p>AAPL is at $192. You want to buy at $189. Place a limit buy at $189. If AAPL dips to $189, your order fills. If it never reaches $189, the order sits unfilled.</p></div>`
          },
          {title:'Stop Orders & Bracket Orders', content:`
            <p class="lesson-text">A <strong>stop-loss order</strong> automatically sells if price falls to your stop level. Protects against large losses.</p>
            <div class="lesson-highlight"><strong>Stop-Loss Rule of Thumb:</strong> Risk no more than 1-2% of your portfolio on any single trade. Set stop losses accordingly.</div>
            <p class="lesson-text">A <strong>bracket order</strong> combines a limit order with both a take-profit AND stop-loss. Your risk/reward is defined upfront.</p>
            <div class="lesson-example"><div class="lesson-example-title">Bracket Order Example</div>
              <p>Buy NVDA at $875. Set:<br>
              Take Profit: $912 (+4.2%)<br>
              Stop Loss: $854 (-2.4%)<br>
              Risk/Reward Ratio: ~1:1.75</p>
            </div>`
          },
        ],
        quiz:[
          { q:'What is the main advantage of a limit order?', opts:['Fastest execution','Guaranteed fill','Price control','Lower commissions'], ans:2, exp:'Limit orders give you price control — you specify the exact price at which you\'re willing to buy or sell, preventing bad fills.' },
          { q:'A stop-loss order is designed to:', opts:['Lock in profits','Automatically buy more','Limit your maximum loss','Get the best price'], ans:2, exp:'A stop-loss exits your position automatically when price falls to your stop level, capping your potential loss.' },
          { q:'What is a bracket order?', opts:['An order to buy and sell simultaneously','An order with both a take-profit and stop-loss','A limit order that brackets the bid-ask spread','Two separate orders placed at the same time'], ans:1, exp:'A bracket order combines an entry with both a take-profit target and stop-loss, completely defining your risk/reward before entering.' },
        ]
      },
      {
        id:'b4', title:'Risk Management 101', time:'8 min', xp:40,
        desc:'The foundation of profitable trading — how to protect your capital.',
        pages:[
          {title:'Why Risk Management Matters', content:`
            <p class="lesson-text">Most new traders focus on <strong>how to make money</strong>. Professional traders focus on <strong>how to not lose money</strong>. The difference is everything.</p>
            <div class="lesson-highlight">If you lose 50% of your account, you need a 100% gain just to break even. Protecting capital is the #1 priority.</div>
            <table class="lesson-table"><tr><th>Loss</th><th>Gain Needed to Recover</th></tr>
              <tr><td>-10%</td><td>+11.1%</td></tr>
              <tr><td>-25%</td><td>+33.3%</td></tr>
              <tr><td>-50%</td><td>+100%</td></tr>
              <tr><td>-75%</td><td>+300%</td></tr>
            </table>`
          },
          {title:'The 1-2% Rule', content:`
            <p class="lesson-text">Risk no more than <strong>1-2% of your total account</strong> on any single trade. This is the most important rule in trading.</p>
            <div class="lesson-formula">Position Size = (Account × Risk%) ÷ (Entry Price - Stop Price)</div>
            <div class="lesson-example"><div class="lesson-example-title">Example</div>
              <p>Account: $10,000. Risk: 1% = $100 max loss per trade.<br>
              Stock at $50, stop at $48 (risk = $2/share).<br>
              Position size = $100 ÷ $2 = 50 shares.<br>
              Even if stopped out, you only lose $100 (1% of account).</p>
            </div>
            <div class="lesson-tip">💡 With 1% risk, you can lose 50 trades in a row and still have $60,500. The math of survival matters!</div>`
          },
          {title:'Diversification & Position Sizing', content:`
            <p class="lesson-text">Don't put all your eggs in one basket. <strong>Diversification</strong> across different stocks, sectors, and strategies reduces your overall risk.</p>
            <ul class="lesson-list">
              <li>Hold 5-20 positions depending on account size</li>
              <li>Spread across multiple sectors (tech, finance, energy, healthcare)</li>
              <li>Mix of different strategies (trend following + mean reversion)</li>
              <li>Keep some cash as "dry powder" for opportunities</li>
            </ul>
            <div class="lesson-highlight"><strong>Correlation risk:</strong> Tech stocks often move together. During a market selloff, SPY, QQQ, AAPL, NVDA all might fall simultaneously. True diversification includes non-correlated assets.</div>`
          },
        ],
        quiz:[
          { q:'If you lose 50% of your account, what return do you need to get back to even?', opts:['+50%','+75%','+100%','+25%'], ans:2, exp:'If you have $10,000 and lose 50%, you have $5,000. To get back to $10,000, you need to double ($5,000 × 2 = $10,000), which is a 100% gain.' },
          { q:'The "1-2% Rule" means:', opts:['Aim for 1-2% daily gains','Risk no more than 1-2% of your account per trade','Only trade 1-2 stocks at a time','Keep 1-2% in cash'], ans:1, exp:'The 1-2% rule means you should never risk more than 1-2% of your total account value on any single trade, limiting maximum losses.' },
          { q:'What is "dry powder" in trading?', opts:['Risky leveraged positions','Reserved cash available for new opportunities','Expired options contracts','A bearish market condition'], ans:1, exp:'Dry powder refers to cash kept in reserve, ready to deploy when great trading opportunities arise without having to liquidate other positions.' },
        ]
      },
      {
        id:'b5', title:'Introduction to Options', time:'10 min', xp:50,
        desc:'What are options, why traders use them, and key terminology.',
        pages:[
          {title:'What Are Options?', content:`
            <p class="lesson-text">An <strong>options contract</strong> gives the buyer the <em>right, but not the obligation</em>, to buy or sell 100 shares of a stock at a specified price before a specified date.</p>
            <div class="lesson-highlight">
              📈 <strong>CALL option:</strong> Right to BUY 100 shares at the strike price<br>
              📉 <strong>PUT option:</strong> Right to SELL 100 shares at the strike price
            </div>
            <p class="lesson-text">Options cost a fraction of owning the stock itself, giving you <strong>leverage</strong>. A $5 option controls $50,000 worth of stock (100 shares × $500).</p>
            <div class="lesson-example"><div class="lesson-example-title">Why Use Options?</div>
              <p>✅ Leverage — control more stock with less money<br>
              ✅ Hedging — protect existing stock positions<br>
              ✅ Income — sell options to collect premium<br>
              ✅ Defined risk — max loss is the premium paid (for buyers)</p>
            </div>`
          },
          {title:'Key Options Terminology', content:`
            <table class="lesson-table"><tr><th>Term</th><th>Definition</th></tr>
              <tr><td>Strike Price</td><td>The price at which you can buy/sell the stock</td></tr>
              <tr><td>Expiration Date</td><td>The date the option expires (worthless if not exercised)</td></tr>
              <tr><td>Premium</td><td>The price you pay for the option contract</td></tr>
              <tr><td>In-the-Money (ITM)</td><td>Option has intrinsic value (call: stock above strike; put: stock below strike)</td></tr>
              <tr><td>Out-of-the-Money (OTM)</td><td>Option has no intrinsic value yet</td></tr>
              <tr><td>At-the-Money (ATM)</td><td>Strike price ≈ current stock price</td></tr>
              <tr><td>Intrinsic Value</td><td>Real, immediate value of the option</td></tr>
              <tr><td>Time Value / Extrinsic</td><td>Premium above intrinsic value; decreases with time</td></tr>
            </table>`
          },
          {title:'Calls vs Puts — Simple Examples', content:`
            <div class="lesson-example"><div class="lesson-example-title">CALL Option Example</div>
              <p>AAPL trades at $189. You buy a $195 Call expiring in 30 days for $2.50.<br>
              Cost: $250 (for 100 shares).<br>
              If AAPL rises to $200, your call is worth ~$5+, giving you a 100%+ gain!<br>
              If AAPL stays below $195, the call expires worthless. Max loss: $250.</p>
            </div>
            <div class="lesson-example"><div class="lesson-example-title">PUT Option Example</div>
              <p>You think SPY will fall. SPY at $445. You buy a $440 Put for $3.00.<br>
              Cost: $300.<br>
              If SPY falls to $430, your put is worth ~$10, a 233% gain!<br>
              If SPY stays above $440, max loss is $300.</p>
            </div>
            <div class="lesson-tip">💡 Try buying a call and a put in the SqueezeSim Trade panel — use the Options mode!</div>`
          },
        ],
        quiz:[
          { q:'A call option gives you the right to:', opts:['Sell 100 shares at the strike price','Buy 100 shares at the strike price','Borrow shares to sell short','Receive dividends'], ans:1, exp:'A call option gives the buyer the right (but not obligation) to BUY 100 shares at the specified strike price before expiration.' },
          { q:'If TSLA is at $250 and you own a $240 Call, your option is:', opts:['Out-of-the-money','At-the-money','In-the-money','Expired'], ans:2, exp:'The $240 call is in-the-money because the stock price ($250) is above the strike price ($240). It has intrinsic value of $10.' },
          { q:'What happens to an options contract at expiration if it\'s out-of-the-money?', opts:['It automatically exercises','The seller pays you','It expires worthless','It converts to stock'], ans:2, exp:'An OTM option at expiration has zero value and expires worthless. The buyer loses the premium paid. This is why options are "wasting assets."' },
        ]
      },
      {
        id:'b6', title:'The Option Greeks — Introduction', time:'10 min', xp:60,
        desc:'Delta, Gamma, Theta, and Vega explained in plain English.',
        pages:[
          {title:'Why Greeks Matter', content:`
            <p class="lesson-text">The "Greeks" are measures that tell you how an option's price changes in response to different market conditions. Understanding them is essential for options trading.</p>
            <div class="lesson-highlight">Greeks are your dashboard — they tell you how your position behaves and what risks you're taking.</div>
            <table class="lesson-table"><tr><th>Greek</th><th>Symbol</th><th>Measures</th></tr>
              <tr><td>Delta</td><td>Δ (Delta)</td><td>Price sensitivity to stock movement</td></tr>
              <tr><td>Gamma</td><td>Γ (Gamma)</td><td>Rate of change of Delta</td></tr>
              <tr><td>Theta</td><td>Θ (Theta)</td><td>Time decay — value lost per day</td></tr>
              <tr><td>Vega</td><td>ν (Vega)</td><td>Sensitivity to implied volatility changes</td></tr>
            </table>`
          },
          {title:'Delta & Gamma', content:`
            <p class="lesson-text"><strong>Delta (Δ)</strong> = how much the option price changes for every $1 move in the stock.</p>
            <div class="lesson-formula">If Delta = 0.50, a $1 stock rise → option rises ~$0.50</div>
            <ul class="lesson-list">
              <li>Call delta: 0 to +1 (ATM ≈ 0.50)</li>
              <li>Put delta: -1 to 0 (ATM ≈ -0.50)</li>
              <li>Deep ITM calls: delta near 1.0 (moves like stock)</li>
              <li>Deep OTM calls: delta near 0 (barely moves)</li>
            </ul>
            <p class="lesson-text"><strong>Gamma (Γ)</strong> = the rate of change of Delta. High gamma means delta changes rapidly (near expiration, near ATM).</p>
            <div class="lesson-tip">💡 0DTE (same-day expiration) options have extremely high gamma. A small stock move can produce massive gains OR losses.</div>`
          },
          {title:'Theta & Vega', content:`
            <p class="lesson-text"><strong>Theta (Θ)</strong> = time decay. How much value the option loses each day (all else equal). Theta is always negative for option buyers.</p>
            <div class="lesson-formula">If Theta = -0.05, you lose $5 per contract per day from time decay alone</div>
            <div class="lesson-highlight">🕐 Time is your enemy when BUYING options. Time is your friend when SELLING options.</div>
            <p class="lesson-text"><strong>Vega (ν)</strong> = sensitivity to Implied Volatility (IV). High vega means option price changes a lot when IV moves.</p>
            <ul class="lesson-list">
              <li>IV rises → option prices increase (buyers profit)</li>
              <li>IV falls → option prices decrease (sellers profit)</li>
              <li>Buy options before expected IV expansion (earnings, news)</li>
              <li>Sell options after IV spikes (IV crush)</li>
            </ul>`
          },
        ],
        quiz:[
          { q:'A call option has a Delta of 0.60. If the stock rises $2, the option price increases approximately:', opts:['$0.60','$1.20','$2.00','$0.30'], ans:1, exp:'Delta × stock move = option price change. 0.60 × $2 = $1.20 per share, or $120 per contract (100 shares × $1.20).' },
          { q:'Theta represents:', opts:['How much delta changes','Price sensitivity to volatility','Daily time decay of an option\'s value','The option\'s leverage ratio'], ans:2, exp:'Theta measures how much value an option loses each day due to the passage of time, assuming all other factors remain constant.' },
          { q:'When would an options buyer MOST benefit from rising Vega (IV)?', opts:['When selling covered calls','Before an expected big news event','When the market is sideways','After earnings are released'], ans:1, exp:'Rising implied volatility inflates option premiums. Buyers benefit from buying options BEFORE events like earnings that cause IV expansion.' },
        ]
      },
      {
        id:'b7', title:'Paper Trading Strategy', time:'6 min', xp:35,
        desc:'How to use paper trading effectively to build real skills.',
        pages:[
          {title:'What is Paper Trading?', content:`
            <p class="lesson-text">Paper trading is practicing with <strong>simulated money</strong> in real market conditions. SqueezeSim gives you a realistic environment to develop skills without risking real capital.</p>
            <div class="lesson-highlight">Studies show traders who paper trade seriously for 3-6 months perform significantly better when they switch to real money.</div>
            <p class="lesson-text">The key is to <strong>treat paper trading like real money</strong>. Every trade, every emotion, every decision should be made as if it were real.</p>`
          },
          {title:'Building a Trading Journal', content:`
            <p class="lesson-text">A trading journal is your most powerful learning tool. Record every trade:</p>
            <ul class="lesson-list">
              <li><strong>Why did you enter?</strong> (thesis, technical setup, catalyst)</li>
              <li><strong>Entry price, stop loss, target</strong></li>
              <li><strong>Position size and % of account</strong></li>
              <li><strong>How did you feel?</strong> (FOMO, fear, confident)</li>
              <li><strong>What happened?</strong> (outcome, what you learned)</li>
            </ul>
            <div class="lesson-tip">💡 Use SqueezeSim's Portfolio page to review all your trades. Look for patterns — which setups work best for you?</div>`
          },
          {title:'Setting Goals & Milestones', content:`
            <p class="lesson-text">Set specific, measurable goals for your paper trading journey:</p>
            <table class="lesson-table"><tr><th>Timeline</th><th>Goal</th></tr>
              <tr><td>Week 1</td><td>Execute 10 trades. Get comfortable with order types.</td></tr>
              <tr><td>Month 1</td><td>Complete all beginner lessons. Achieve positive P&L.</td></tr>
              <tr><td>Month 2</td><td>Try options trading. Complete intermediate lessons.</td></tr>
              <tr><td>Month 3</td><td>Develop a consistent strategy. 60%+ win rate goal.</td></tr>
              <tr><td>Month 6</td><td>Complete all lessons. Ready for real money consideration.</td></tr>
            </table>
            <div class="lesson-warning">⚠️ Never trade real money until you've been consistently profitable in paper trading for at least 3 months.</div>`
          },
        ],
        quiz:[
          { q:'What\'s the most important rule when paper trading?', opts:['Trade as much as possible','Treat it exactly like real money','Take bigger risks since it\'s not real','Focus only on winning trades'], ans:1, exp:'Paper trading only builds real skills if you treat it seriously. The emotional and decision-making habits you build in paper trading transfer to real trading.' },
          { q:'A trading journal helps you:', opts:['Get tips from others','Avoid all losing trades','Identify patterns in your trading behavior','Predict future market moves'], ans:2, exp:'A trading journal reveals patterns in your trading — what setups work, what emotions affect your decisions, and how to improve over time.' },
        ]
      },
      {
        id:'b8', title:'Your First Trade Walkthrough', time:'8 min', xp:50,
        desc:'Step-by-step guide to executing your first trade in SqueezeSim.',
        pages:[
          {title:'Choosing a Stock', content:`
            <p class="lesson-text">For your first trade, let's use a familiar, liquid stock. We recommend starting with an ETF like SPY (S&P 500) or QQQ (NASDAQ 100).</p>
            <div class="lesson-highlight"><strong>Why ETFs first?</strong> They're highly liquid (easy to buy/sell), represent the broad market, and are less volatile than individual stocks.</div>
            <p class="lesson-text">In SqueezeSim, go to the <strong>Trade</strong> page. Select <strong>SPY</strong> from the symbol selector at the top.</p>
            <ol class="lesson-list">
              <li>Look at the current price and daily change</li>
              <li>Check the volume — is it normal or unusually high?</li>
              <li>Review the chart — is price going up, down, or sideways?</li>
            </ol>`
          },
          {title:'Placing the Trade', content:`
            <p class="lesson-text">For your first trade, we'll use a <strong>Market Buy Order</strong>:</p>
            <ol class="lesson-list">
              <li>Select <strong>SPY</strong> as your symbol</li>
              <li>Click <strong>BUY</strong> tab (should be green)</li>
              <li>Order type: <strong>Market Order</strong></li>
              <li>Quantity: Start with <strong>10 shares</strong></li>
              <li>Click <strong>"25%" button</strong> to see what 25% of your capital buys</li>
              <li>Check the <strong>Risk Calculator</strong> — see your estimated cost</li>
              <li>Click <strong>BUY — MARKET ORDER</strong></li>
            </ol>
            <div class="lesson-highlight">After executing, check the <strong>Dashboard</strong> to see your open position appear under "Open Positions."</div>`
          },
          {title:'Managing and Closing', content:`
            <p class="lesson-text">Now you have an open position. Here's how to manage it:</p>
            <ul class="lesson-list">
              <li>Watch the <strong>Unrealized P&L</strong> update as the price moves</li>
              <li>When you're ready to close, go back to Trade page</li>
              <li>Select <strong>SPY</strong>, click the <strong>SELL</strong> tab</li>
              <li>Set quantity equal to your position size</li>
              <li>Execute a market sell order</li>
            </ul>
            <div class="lesson-tip">💡 After closing, check your Portfolio page. Your trade appears in Trade History with full P&L details. Congratulations — you've made your first trade!</div>
            <div class="lesson-highlight">🏆 You're now on track to earn the "First Blood" achievement!</div>`
          },
        ],
        quiz:[
          { q:'For a beginner\'s first trade, which is the safest choice?', opts:['AMC (meme stock)','NVDA (volatile tech)','SPY (S&P 500 ETF)','MRNA (biotech)'], ans:2, exp:'SPY tracks the S&P 500 and is one of the most liquid, stable starting points. It\'s the market benchmark and behaves predictably relative to individual stocks.' },
          { q:'After executing a buy order, where can you see your open position?', opts:['In the Market tab','Under Open Positions on the Dashboard','In the Academy','In the Leaderboard'], ans:1, exp:'Open positions appear on the Dashboard under "Open Positions" and also in the Trade page showing real-time P&L.' },
        ]
      },
    ],

    intermediate: [
      {
        id:'i1', title:'Technical Analysis Deep Dive', time:'12 min', xp:75,
        desc:'RSI, MACD, moving averages, Bollinger Bands, and how to use them.',
        pages:[
          {title:'Moving Averages', content:`
            <p class="lesson-text">A <strong>Moving Average (MA)</strong> smooths out price action to show the underlying trend. Two key types:</p>
            <div class="lesson-highlight"><strong>Simple Moving Average (SMA):</strong> Average of last N closing prices<br><strong>Exponential Moving Average (EMA):</strong> Gives more weight to recent prices, reacts faster</div>
            <p class="lesson-text">Popular combinations: 9/21 EMA (short-term), 50/200 SMA (long-term)</p>
            <div class="lesson-formula">Golden Cross: 50 SMA crosses ABOVE 200 SMA = Bullish signal<br>Death Cross: 50 SMA crosses BELOW 200 SMA = Bearish signal</div>`
          },
          {title:'RSI — Relative Strength Index', content:`
            <p class="lesson-text">RSI measures momentum on a scale of 0-100. Classic interpretation:</p>
            <ul class="lesson-list">
              <li><strong>RSI > 70:</strong> Overbought — potential reversal down</li>
              <li><strong>RSI < 30:</strong> Oversold — potential reversal up</li>
              <li><strong>RSI 50:</strong> Neutral / midline</li>
            </ul>
            <div class="lesson-tip">💡 In trending markets, RSI can stay overbought/oversold for extended periods. Use RSI divergence (price makes new high but RSI doesn't) for stronger signals.</div>`
          },
          {title:'MACD & Bollinger Bands', content:`
            <p class="lesson-text"><strong>MACD (Moving Average Convergence Divergence)</strong> shows trend direction and momentum through two EMAs (12 and 26 period) and a signal line (9 EMA of MACD).</p>
            <div class="lesson-highlight">MACD line crosses above Signal line = Bullish<br>MACD line crosses below Signal line = Bearish</div>
            <p class="lesson-text"><strong>Bollinger Bands</strong> use a 20-period SMA with bands 2 standard deviations above and below. They show volatility and potential breakouts.</p>
            <ul class="lesson-list"><li>Price touching upper band = potentially overbought</li><li>Price touching lower band = potentially oversold</li><li>Band squeeze (tight bands) = low volatility, breakout likely</li></ul>`
          },
        ],
        quiz:[
          { q:'What does a "Golden Cross" signal?', opts:['Bearish reversal','The 50 SMA crossing above the 200 SMA','The stock hitting all-time highs','High trading volume'], ans:1, exp:'A Golden Cross occurs when the shorter 50-day SMA crosses above the longer 200-day SMA, generally considered a bullish signal for long-term trend.' },
          { q:'RSI reading of 25 suggests:', opts:['Strong uptrend','Overbought conditions','Oversold conditions — potential bounce','Maximum fear'], ans:2, exp:'RSI below 30 indicates oversold conditions, suggesting the asset may be due for a bounce or reversal upward. It means recent selling was excessive.' },
        ]
      },
      {
        id:'i2', title:'Advanced Options Strategies', time:'15 min', xp:90,
        desc:'Spreads, straddles, iron condors, and when to use each.',
        pages:[
          {title:'Vertical Spreads', content:`
            <p class="lesson-text">Vertical spreads involve buying one option and selling another at a different strike, same expiration.</p>
            <div class="lesson-highlight"><strong>Bull Call Spread:</strong> Buy lower call + Sell higher call → Bullish, limited risk, limited profit<br><strong>Bear Put Spread:</strong> Buy higher put + Sell lower put → Bearish, limited risk, limited profit</div>
            <div class="lesson-example"><div class="lesson-example-title">Why use spreads instead of naked options?</div>
              <p>A long call on SPY @ $445 strike costs $5.00 ($500 per contract).<br>
              A $445/$455 bull call spread costs $2.50 ($250 per contract).<br>
              Same directional exposure, 50% less cost! The tradeoff: profit is capped at $455.</p>
            </div>`
          },
          {title:'Straddles & Strangles', content:`
            <p class="lesson-text">These strategies profit from <strong>big moves in either direction</strong> — perfect for earnings season.</p>
            <div class="lesson-formula">Straddle = Buy ATM Call + Buy ATM Put (same strike)<br>Strangle = Buy OTM Call + Buy OTM Put (different strikes)</div>
            <table class="lesson-table"><tr><th></th><th>Straddle</th><th>Strangle</th></tr>
              <tr><td>Cost</td><td>More expensive</td><td>Cheaper</td></tr>
              <tr><td>Break-even</td><td>Narrower range</td><td>Wider range needed</td></tr>
              <tr><td>Best for</td><td>High-impact events</td><td>Moderate move expected</td></tr>
            </table>`
          },
          {title:'Iron Condor — The Income Machine', content:`
            <p class="lesson-text">The iron condor is one of the most popular income strategies, designed to profit in <strong>range-bound markets</strong>.</p>
            <div class="lesson-formula">Iron Condor = Sell OTM Call Spread + Sell OTM Put Spread</div>
            <div class="lesson-example"><div class="lesson-example-title">SPY Iron Condor Example</div>
              <p>SPY at $445. 30 days to expiration.<br>
              Sell $460/$465 Call Spread → Collect $0.80<br>
              Sell $430/$425 Put Spread → Collect $0.80<br>
              Total Credit: $1.60 ($160 per condor)<br>
              Max profit: $1.60 if SPY stays between $430-$460<br>
              Max loss: $5.00 - $1.60 = $3.40 ($340) if either side breaches</p>
            </div>
            <div class="lesson-tip">💡 Iron condors have ~70% probability of profit. They're a core strategy for professional options sellers.</div>`
          },
        ],
        quiz:[
          { q:'A bull call spread is best used when:', opts:['You expect the stock to fall sharply','You expect a moderate rise in the stock','You expect no movement','You expect a massive spike'], ans:1, exp:'Bull call spreads are for moderately bullish outlooks. They profit from upward movement but cap the profit at the higher strike, making them more efficient than naked calls.' },
          { q:'An iron condor profits when:', opts:['The stock makes a huge move','The stock stays within a defined range','IV increases significantly','Earnings beat expectations'], ans:1, exp:'Iron condors profit when the stock stays within the range between your sold strikes. The trader collects premium and keeps it all if price stays in the zone.' },
        ]
      },
    ],

    professional: [
      {
        id:'p1', title:'Portfolio Management & Advanced Risk', time:'15 min', xp:100,
        desc:'Sharpe ratio, drawdown, correlation, portfolio construction.',
        pages:[
          {title:'Key Performance Metrics', content:`
            <p class="lesson-text">Professional traders measure performance with precise metrics, not just "did I make money?"</p>
            <table class="lesson-table"><tr><th>Metric</th><th>What It Measures</th><th>Target</th></tr>
              <tr><td>Sharpe Ratio</td><td>Return per unit of risk</td><td>> 1.0 (> 2.0 is excellent)</td></tr>
              <tr><td>Max Drawdown</td><td>Largest peak-to-trough loss</td><td>< 20% for most strategies</td></tr>
              <tr><td>Win Rate</td><td>% of profitable trades</td><td>40-60% is normal</td></tr>
              <tr><td>Profit Factor</td><td>Gross profit ÷ Gross loss</td><td>> 1.5 is good</td></tr>
              <tr><td>Calmar Ratio</td><td>Annual return ÷ Max drawdown</td><td>> 1.0</td></tr>
            </table>
            <div class="lesson-highlight"><strong>Key insight:</strong> A 40% win rate CAN be profitable if your average winner is 3x your average loser. It's about expectancy, not win rate alone.</div>`
          },
          {title:'Correlation & Portfolio Construction', content:`
            <p class="lesson-text">Correlation measures how assets move together. -1.0 = perfectly inverse, +1.0 = perfectly correlated, 0 = no relationship.</p>
            <div class="lesson-formula">Portfolio Volatility = √(w₁²σ₁² + w₂²σ₂² + 2w₁w₂σ₁σ₂ρ₁₂)</div>
            <p class="lesson-text">The goal is to combine assets with low or negative correlation to reduce overall portfolio volatility.</p>
            <ul class="lesson-list">
              <li>AAPL and MSFT: High positive correlation (~0.80)</li>
              <li>SPY and TLT (bonds): Often negative correlation</li>
              <li>SPY and GLD (gold): Low correlation (~0.10)</li>
            </ul>
            <div class="lesson-highlight">Modern Portfolio Theory: The "efficient frontier" shows the optimal portfolio mix for maximum return at each risk level.</div>`
          },
          {title:'Advanced Risk Management', content:`
            <p class="lesson-text">Professional risk management goes beyond stop-losses:</p>
            <ul class="lesson-list">
              <li><strong>VAR (Value at Risk):</strong> Maximum expected loss with 95% confidence over N days</li>
              <li><strong>Stress Testing:</strong> How would your portfolio perform in a 2008-style crash? COVID March 2020?</li>
              <li><strong>Delta Hedging:</strong> Using options to neutralize directional exposure</li>
              <li><strong>Sector Concentration Limits:</strong> No more than 30% in any single sector</li>
              <li><strong>Leverage Limits:</strong> Gross exposure < 200% of capital</li>
            </ul>
            <div class="lesson-warning">⚠️ Even the best strategies can have 10-20 losing trades in a row. Size appropriately so you can survive the drawdown and keep trading.</div>`
          },
        ],
        quiz:[
          { q:'A Sharpe Ratio of 2.5 indicates:', opts:['50% win rate','High returns with manageable risk','The portfolio lost money','Excessive leverage'], ans:1, exp:'A Sharpe Ratio above 2.0 is excellent, indicating the strategy generates strong returns relative to the risk taken. Most professional funds target Sharpe > 1.0.' },
          { q:'What does low correlation between assets achieve?', opts:['Higher individual returns','Reduced portfolio volatility through diversification','Guaranteed profits','Higher leverage'], ans:1, exp:'Low or negative correlation between assets means they don\'t move together, reducing overall portfolio volatility without sacrificing expected returns.' },
        ]
      },
    ],
  };

  function init() {
    // Check for new lessons
    const done = _state.gamification.beginnerLessonsComplete || 0;
    if (done < CURRICULUM.beginner.length) {
      $('academy-dot').style.display = 'block';
    }
  }

  function setLevel(level, btn) {
    _level = level;
    document.querySelectorAll('.alt').forEach(b => b.classList.remove('active'));
    if (btn) btn.classList.add('active');
    render();
  }

  function render() {
    const lessons = CURRICULUM[_level] || [];
    const done    = _state.gamification.beginnerLessonsComplete || 0;

    // Progress overview
    const overview = $('academy-progress-overview');
    if (overview) {
      const total = lessons.length;
      const completed = lessons.filter(l => isCompleted(l.id)).length;
      const pct = total ? Math.round(completed / total * 100) : 0;
      overview.innerHTML = `
        <div class="apo-header">
          <div><div class="apo-level">${_level.toUpperCase()} TRACK</div><div style="font-size:11px;color:var(--text2);margin-top:2px">${completed} of ${total} lessons complete</div></div>
          <div class="apo-pct">${pct}%</div>
        </div>
        <div class="apo-bar-bg"><div class="apo-bar-fill" style="width:${pct}%"></div></div>
        <div class="apo-stats">
          <span class="apo-stat">XP: <strong>${lessons.filter(l=>isCompleted(l.id)).reduce((a,l)=>a+l.xp,0)} / ${lessons.reduce((a,l)=>a+l.xp,0)}</strong></span>
          <span class="apo-stat">Quizzes: <strong>${completed}/${total}</strong></span>
          <span class="apo-stat">Est. Time: <strong>${lessons.reduce((a,l)=>a+parseInt(l.time),0)} min total</strong></span>
        </div>`;
    }

    // Lesson grid
    const grid = $('academy-grid');
    if (!grid) return;
    grid.innerHTML = lessons.map((lesson, i) => {
      const comp = isCompleted(lesson.id);
      const locked = _level === 'professional' && !tierAllows('pro') && i > 0;
      return `<div class="lesson-card ${comp?'completed':''} ${locked?'locked':''}" onclick="${locked?'SimApp.showUpgradeModal(\'pro\')':''`openLesson('${lesson.id}')`}">
        <div class="lc-num">LESSON ${i+1}</div>
        <div class="lc-title">${lesson.title}</div>
        <div class="lc-desc">${lesson.desc}</div>
        <div class="lc-progress"><div class="lc-prog-fill" style="width:${comp?100:0}%"></div></div>
        <div class="lc-footer">
          <span class="lc-time">⏱ ${lesson.time}</span>
          <span class="lc-xp">${comp?'✓':'+'}${lesson.xp} XP</span>
        </div>
      </div>`;
    }).join('');
  }

  function tierAllows(tier) {
    const order = { free:0, starter:1, pro:2, elite:3 };
    return (order[_state.subscription]||0) >= (order[tier]||0);
  }

  function isCompleted(id) {
    return (_state.gamification.completedLessons || []).includes(id);
  }

  function openLesson(id) {
    const lessons = [...CURRICULUM.beginner, ...CURRICULUM.intermediate, ...CURRICULUM.professional];
    _lesson = lessons.find(l => l.id === id);
    if (!_lesson) return;
    _page = 0;

    $('view-academy').style.display = 'block';
    $('academy-grid').style.display = 'none';
    $('academy-progress-overview').style.display = 'none';
    $('academy-level-tabs').style.display = 'none';
    const lv = $('lesson-view');
    if (lv) lv.style.display = 'block';

    $('lesson-breadcrumb').textContent = `${_level.charAt(0).toUpperCase()+_level.slice(1)} › ${_lesson.title}`;
    $('lesson-xp-badge').textContent = `+${_lesson.xp} XP`;

    renderPage();
  }

  function renderPage() {
    const pages = _lesson.pages;
    const page  = pages[_page];
    const body  = $('lesson-body');
    if (!body || !page) return;

    body.innerHTML = `<div class="lesson-content-page active">
      <div class="lesson-title">${page.title}</div>
      <div class="lesson-subtitle">${_lesson.title} — Page ${_page+1} of ${pages.length}</div>
      ${page.content}
    </div>`;

    // Dots
    const dotsEl = $('lesson-dots');
    if (dotsEl) {
      dotsEl.innerHTML = pages.map((_,i) =>
        `<div class="lesson-dot ${i===_page?'active':i<_page?'done':''}" onclick="Academy.goPage(${i})"></div>`
      ).join('');
    }

    const prevBtn = $('lprev-btn');
    const nextBtn = $('lnext-btn');
    if (prevBtn) prevBtn.style.display = _page > 0 ? 'block' : 'none';
    if (nextBtn) {
      if (_page === pages.length - 1) {
        nextBtn.textContent = '📝 Take Quiz →';
      } else {
        nextBtn.textContent = 'Next →';
      }
    }
  }

  function nextPage() {
    if (_page < _lesson.pages.length - 1) {
      _page++;
      renderPage();
    } else {
      startQuiz();
    }
  }

  function prevPage() {
    if (_page > 0) { _page--; renderPage(); }
  }

  function goPage(n) { _page = n; renderPage(); }

  function startQuiz() {
    _quizData  = _lesson.quiz;
    _quizIdx   = 0;
    _quizScore = 0;
    $('lesson-view').style.display = 'none';
    const qv = $('quiz-view');
    if (qv) qv.style.display = 'block';
    $('quiz-title').textContent = `${_lesson.title} — Quiz`;
    renderQuizQuestion();
  }

  function renderQuizQuestion() {
    if (_quizIdx >= _quizData.length) { finishQuiz(); return; }
    const q = _quizData[_quizIdx];
    const pct = Math.round(_quizIdx / _quizData.length * 100);
    $('quiz-prog-fill').style.width = pct + '%';
    $('quiz-score-badge').textContent = `${_quizScore}/${_quizData.length}`;
    $('quiz-body').innerHTML = `
      <div class="quiz-question">Q${_quizIdx+1}. ${q.q}</div>
      <div class="quiz-options">
        ${q.opts.map((opt, i) => `<button class="quiz-option" onclick="Academy.answerQuiz(${i})">${opt}</button>`).join('')}
      </div>`;
  }

  function answerQuiz(idx) {
    const q = _quizData[_quizIdx];
    const btns = document.querySelectorAll('.quiz-option');
    btns.forEach((b, i) => {
      b.classList.add('disabled');
      if (i === q.ans) b.classList.add('correct');
      else if (i === idx && idx !== q.ans) b.classList.add('wrong');
    });
    if (idx === q.ans) _quizScore++;
    $('quiz-body').innerHTML += `<div class="quiz-explanation">💡 ${q.exp}<br><button class="btn-primary quiz-next-btn" onclick="Academy.nextQuestion()">Next →</button></div>`;
  }

  function nextQuestion() {
    _quizIdx++;
    renderQuizQuestion();
  }

  function finishQuiz() {
    const passed = _quizScore / _quizData.length >= 0.7;
    if (passed) {
      if (!isCompleted(_lesson.id)) {
        if (!_state.gamification.completedLessons) _state.gamification.completedLessons = [];
        _state.gamification.completedLessons.push(_lesson.id);
        _state.gamification.beginnerLessonsComplete = (_state.gamification.completedLessons||[]).filter(id=>id.startsWith('b')).length;
        SimEngine.awardXP(_lesson.xp, `Lesson: ${_lesson.title}`);
        SimEngine.checkAchievements();
        SimEngine.saveState();
      }
    }
    $('quiz-body').innerHTML = `
      <div style="text-align:center;padding:40px">
        <div style="font-size:64px;margin-bottom:16px">${passed?'🏆':'📚'}</div>
        <h2 style="font-size:22px;font-weight:900;color:#fff;margin-bottom:8px">${passed?'Lesson Complete!':'Keep Studying!'}</h2>
        <div style="font-size:28px;font-weight:900;font-family:var(--mono);color:${passed?'#00ff88':'#ff4757'};margin-bottom:8px">${_quizScore}/${_quizData.length} Correct</div>
        ${passed?`<div style="color:#ffe600;font-family:var(--mono);font-weight:700;margin-bottom:20px">+${_lesson.xp} XP Earned!</div>`:'<p style="color:var(--text2);margin-bottom:20px">Score 70%+ to earn XP. Review the lesson and try again.</p>'}
        <button class="btn-primary" onclick="Academy.backToList()" style="margin-right:8px">Back to Academy</button>
        <button class="btn-glass" onclick="Academy.retakeLesson()">Review Lesson</button>
      </div>`;
  }

  function exitQuiz() { backToList(); }

  function retakeLesson() {
    $('quiz-view').style.display = 'none';
    _page = 0;
    $('lesson-view').style.display = 'block';
    renderPage();
  }

  function backToList() {
    $('lesson-view').style.display = 'none';
    $('quiz-view').style.display = 'none';
    $('academy-grid').style.display = 'grid';
    $('academy-progress-overview').style.display = 'block';
    $('academy-level-tabs').style.display = 'flex';
    render();
  }

  return { init, setLevel, render, openLesson, nextPage, prevPage, goPage, answerQuiz, nextQuestion, exitQuiz, retakeLesson, backToList };
})();
