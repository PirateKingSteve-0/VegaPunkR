HTTP Streaming

# HTTP Streaming

Stream market updates using HTTP streaming. You will receive a different payload depending on the market event that occurred. Details about each event can be found in the response definition.

Note: In order to stream data, you must first create a streaming session. Upon receiving a sessionid, you will have up to 5 minutes to connect to a streaming endpoint before the session expires.

Note that streaming uses a different endpoint: [https://stream.tradier.com](https://stream.tradier.com)

For HTTP streaming, you can use GET or POST methods to initiate a stream. GET is more concise and will allow for a shorter list of symbols in the query, while POST can be used for a longer list of symbols. Both will return the same streaming data.

## GET

```
GET https://stream.tradier.com/v1/markets/events
```

### Headers

| Header        | Required | Values/Example                    | Default         |
| ------------- | -------- | --------------------------------- | --------------- |
| Accept        | Optional | application/json, application/xml | application/xml |
| Authorization | Required | Bearer  \<API TOKEN>              | N/A             |

### Parameters

The following parameters can be used to filter the results:

| Parameter       | Type  | Param Type | Required | Values/Example                        | Default      |
| --------------- | ----- | ---------- | -------- | ------------------------------------- | ------------ |
| symbols         | Query | String     | Yes      | "AAPL, TSLA250815C00150000"           | N/A          |
| sessionid       | Query | String     | Yes      | "9D1C7018CFEB6F8ECF8CAA58B33"         | N/A          |
| filter          | Query | String     | No       | "trade,quote,summary,timesale,tradex" | All payloads |
| linebreak       | Query | String     | No       | "true"                                | "false"      |
| validOnly       | Query | String     | No       | "true"                                | "true"       |
| advancedDetails | Query | String     | No       | "true"                                | "false"      |

### Code Example

```
​import json
​import requests

headers = {
  'Accept': 'application/json'
}

payload = { 
  'sessionid': 'SESSION_ID',
  'symbols': 'SPY',
  'linebreak': True
}

r = requests.get('https://stream.tradier.com/v1/markets/events', stream=True, params=payload, headers=headers)
for line in r.iter_lines():
  if line:
    print(json.loads(line))
```

### Return Example

```
{
  "type": "quote",
  "symbol": "SPY",
  "bid": 281.84,
  "bidsz": 60,
  "bidexch": "M",
  "biddate": "1557757189000",
  "ask": 281.85,
  "asksz": 6,
  "askexch": "Z",
  "askdate": "1557757190000"
}
{
  "type": "trade",
  "symbol": "SPY",
  "exch": "J",
  "price": "281.85",
  "size": "100",
  "cvol": "27978993",
  "date": "1557757190000",
  "last": "281.85"
}
{
  "type": "summary",
  "symbol": "SPY",
  "open": "282.42",
  "high": "283.49",
  "low": "281.07",
  "prevClose": "288.1"
}
{
  "type": "timesale",
  "symbol": "SPY",
  "exch": "Q",
  "bid": "282.08",
  "ask": "282.09",
  "last": "282.09",
  "size": "100",
  "date": "1557758874355",
  "seq": 352795,
  "flag": "",
  "cancel": false,
  "correction": false,
  "session": "normal"
}
{
  "type": "tradex",
  "symbol": "SPY",
  "exch": "J",
  "price": "281.85",
  "size": "100",
  "cvol": "27978993",
  "date": "1557757190000",
  "last": "281.85"
}
```

## POST

```
POST https://stream.tradier.com/v1/markets/events
```

### Headers

| Header        | Required | Values/Example                    | Default         |
| ------------- | -------- | --------------------------------- | --------------- |
| Accept        | Optional | application/json, application/xml | application/xml |
| Authorization | Required | Bearer  \<API TOKEN>              | N/A             |

### Parameters

| Parameter       | Type | Param Type | Required | Values/Example                        | Default      |
| --------------- | ---- | ---------- | -------- | ------------------------------------- | ------------ |
| symbols         | Form | String     | Yes      | "AAPL, TSLA250815C00150000"           | N/A          |
| sessionid       | Form | String     | Yes      | "9D1C7018CFEB6F8ECF8CAA58B33"         | N/A          |
| filter          | Form | String     | No       | "trade,quote,summary,timesale,tradex" | All payloads |
| linebreak       | Form | String     | No       | "true"                                | "false"      |
| validOnly       | Form | String     | No       | "true"                                | "true"       |
| advancedDetails | Form | String     | No       | "true"                                | "false"      |

### Code Example

```
​import json
​import requests

headers = {
  'Accept': 'application/json'
}

payload = { 
  'sessionid': 'SESSION_ID',
  'symbols': 'SPY',
  'linebreak': True
}

r = requests.post('https://stream.tradier.com/v1/markets/events', stream=True, params=payload, headers=headers)
for line in r.iter_lines():
  if line:
```

### Return Example

```
{
  "type": "quote",
  "symbol": "SPY",
  "bid": 281.84,
  "bidsz": 60,
  "bidexch": "M",
  "biddate": "1557757189000",
  "ask": 281.85,
  "asksz": 6,
  "askexch": "Z",
  "askdate": "1557757190000"
}
{
  "type": "trade",
  "symbol": "SPY",
  "exch": "J",
  "price": "281.85",
  "size": "100",
  "cvol": "27978993",
  "date": "1557757190000",
  "last": "281.85"
}
{
  "type": "summary",
  "symbol": "SPY",
  "open": "282.42",
  "high": "283.49",
  "low": "281.07",
  "prevClose": "288.1"
}
{
  "type": "timesale",
  "symbol": "SPY",
  "exch": "Q",
  "bid": "282.08",
  "ask": "282.09",
  "last": "282.09",
  "size": "100",
  "date": "1557758874355",
  "seq": 352795,
  "flag": "",
  "cancel": false,
  "correction": false,
  "session": "normal"
}
```