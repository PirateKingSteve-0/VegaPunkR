Getting Started Trading

# Getting Started Trading

<br />

Getting Started with Trading

We tried our best to make the trading API as easy as possible to work with. There are some essential concepts to understand having to do with a trading flow, but the calls themselves are very straightforward.

### Buying and Selling Equities

Placing an order through the Trading API is very simple. There’s no FIXML to learn, no custom formats or XML. There are five required parameters:

* class - The kind of order to be placed. One of: equity, option, multileg, combo
* symbol - The symbol to be ordered.
* duration - The time for which the order will be remain in effect (Day or GTC).
* side - The side of the order (buy or sell).
* quantity - The number of shares to be ordered, in whole numbers.
* type - The type of order to be placed (market, limit, etc.)
* A properly composed order for 100 shares of AAPL looks like this:

POST /v1/accounts/12345678/orders HTTP/1.1
Host: api.tradier.com
Accept: */*

class=equity\&symbol=AAPL\&duration=day\&side=buy\&quantity=100\&type=market

<br />

### Buying and Selling Options

Placing an order for an option is very similar to that of a stock. There is only one additional field for placing a single-leg:

option\_symbol an OCC symbol (AAPL140118C00195000) for the option to be ordered.
A properly composed order for 100 shares of an AAPL option looks like this:

POST /v1/accounts/12345678/orders HTTP/1.1
Host: api.tradier.com
Accept: */*

class=option\&symbol=AAPL\&duration=day\&side=sell\_to\_open\&quantity=100
\&type=market\&option\_symbol=AAPL140118C00195000

<br />

### Placing Multileg and Combo orders

Placing multileg and combo orders uses the same framework and parameters as explained above for single leg orders with only slight modification. Legs only have a three specific data points: side, quantity, and symbol. For option legs you should send option\_symbol, in the instance of combo orders, equity legs should have option\_symbol set to null as the underlying symbol will be used.

In order to send multiple legs, we’ve adopted standard form-parameter notation: side\[index], quantity\[index], option\_symbol\[index], where index is the leg number (based at zero).

* side\[index] the side of the leg.
* quantity\[index] the quantity of shares/contracts for that leg
* option\_symbol\[index] the OCC symbol (AAPL140118C00195000) for the option. Should be null for equity legs.

A properly composed multileg order (spread) looks like this:

POST /v1/accounts/12345678/orders HTTP/1.1
Host: api.tradier.com
Accept: */*

class=multileg\&symbol=CSCO\&duration=day\&type=market
\&side\[0]=buy\_to\_open\&quantity\[0]=1\&option\_symbol\[0]=CSCO150117C00035000
\&side\[1]=sell\_to\_open\&quantity\[1]=1\&option\_symbol\[1]=CSCO140118C00008000

<br />

### Pre/Post Market Sessions

Pre and Post market session orders are supported, however some restrictions apply.

Pre-market Session: 7:00AM EST to 9:24AM EST
Post-market Session: 4:00PM EST to 19:55PM EST

Some notes about orders placed for these sessions:

* Only equity orders are permitted.
* Order type must be limit
* Orders placed in the session will expire at the end of the session
* You cannot place orders for pre/post session outside the session window

<br />

### Previewing Orders

It is in the investor’s best interest to preview an order before actually placing it. A preview call will return issues and warnings associated with the order (if applicable) as well as commission information should the order be executed. Previewing is also the best way to get started using the Trading API.

By sending preview=true as a parameter to the Create Order call, you can place “pretend” calls to these APIs.

Note: Preview orders are not required — but are recommended. There will be circumstances (i.e. algorithmic trading) where it is unreasonable to preview the order first.

### Market Data

Market data is key to placing accurate trades. As a developer, you’re responsible for making market data requests in order to give users enough information before placing a trade.