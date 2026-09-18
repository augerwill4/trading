# GEX Lab — Project Rules
## Purpose
Personal research tool. Computes daily dealer gamma exposure (GEX) levels from free delayed options data across a broad universe of liquid optionable tickers (indexes, ETFs, and single stocks), and journals my trades tagged with the day's gamma regime so I can test where, if anywhere, regime affects my results.
## Hard rules
- NEVER write code that places orders, connects to a brokerage, or stores broker credentials. Analysis only.
- No paid APIs or API keys unless I explicitly approve.
- Every GEX model assumption must be commented in code AND listed in README.md under "Model Assumptions".
- Python 3, minimal dependencies (pandas, numpy, scipy, requests, matplotlib).
- Respect free data sources: rate-limit requests, cache responses, retry with backoff, never hammer an endpoint.
- Write tests for the math and run them before saying a task is done.
- Explain changes in plain English after each task.
## Universe
Dynamic, built by the liquidity scanner (see universe.py). Always includes SPY, QQQ, SPX, IWM plus everything in watchlist.txt.
