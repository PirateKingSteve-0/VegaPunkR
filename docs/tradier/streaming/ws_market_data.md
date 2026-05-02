Websocket Market Data Streaming

# Websocket Market Data Streaming

Stream market updates using WebSocket streaming. You will receive a different payload depending on the market event that occurred. Details about each event can be found in the response definition. You can continually update the data in your stream by resending this request with different parameters.

Note: In order to stream data, you must first create a streaming session. Upon receiving a sessionid, you will have up to 5 minutes to connect to a streaming endpoint before the session expires.

Once connected and streaming data, to make modifications to your current streaming connection, simply resend your request payload using the existing sessionid. You can change the symbols by resending your payload with an updated list of symbols and we’ll adjust your stream accordingly. Note: if your sessionid has expired, you will need to get a new one and send it with your adjusted payload.

While we do not publish the symbol limits for these APIs, we do monitor for abuse to make sure people aren’t doing anything egregious (like asking for an entire exchange worth of symbols). Essentially, ask for what you need. Don’t abuse the APIs and you should be fine. It is not permitted to open more than one session at a time.

<br />

Note that WebSocket streaming uses a different endpoint: wss\://ws.tradier.com

WebSocket

```
wss://ws.tradier.com/v1/markets/events
```

<br />

### Parameters

| Parameter       | Type | Param Type | Detail                                                            | Required | Values/Example                                   | Default      |
| --------------- | ---- | ---------- | :---------------------------------------------------------------- | -------- | ------------------------------------------------ | ------------ |
| symbols         | JSON | Array      | An array list of symbols (equity or option)                       | Yes      | \["AAPL, TSLA250815C00150000"]                   | N/A          |
| sessionid       | JSON | String     | Session Id retrieved from the create session endpoint             | Yes      | "9D1C7018CFEB6F8ECF8CAA58B33"                    | N/A          |
| filter          | JSON | Array      | An array list of the types of payloads to retrieve in the stream. | No       | \["trade","quote","summary","timesale","tradex"] | All payloads |
| linebreak       | JSON | Boolean    | Insert a line break after a completed payload                     | No       | "true"                                           | "false"      |
| validOnly       | JSON | Boolean    | Include only ticks that are considered valid by exchanges.        | No       | "true"                                           | "true"       |
| advancedDetails | JSON | Boolean    | Include advanced details in timesale payloads                     | No       | "true"                                           | "false"      |

<br />

### Code Example

```python
import asyncio
import websockets

async def ws_connect():
    uri = "wss://ws.tradier.com/v1/markets/events"
    async with websockets.connect(uri, ssl=True, compression=None) as websocket:
        payload = '{"symbols": ["SPY"], "filter": ["quote"], "sessionid": "SESSION_ID", "linebreak": true}'
        await websocket.send(payload)

        print(f">>> {payload}")

        async for message in websocket:
            print(f"<<< {message}")

asyncio.run(ws_connect())
```

```node
const WebSocket = require('ws');
const ws = new WebSocket('wss://ws.tradier.com/v1/markets/events');

ws.on('open', function open() {
  console.log('Connected, sending subscription commands...');
  ws.send('{"symbols": ["SPY"], "filter": ["trade"], "sessionid": "SESSION_ID", "linebreak": true}');
});
ws.on('message', function incoming(data) {
  console.log(data);
});
ws.on('error', function error(data) {
  console.log(data);
});
```

```java
import org.java_websocket.client.WebSocketClient;
import org.java_websocket.handshake.ServerHandshake;

import java.net.URI;
import java.net.URISyntaxException;

/**
* This example uses org.java-websocket.Java-WebSocket version 1.4.1
*
* For more details, please access https://github.com/TooTallNate/Java-WebSocket
* */
public class Main {
  public static void main(String[] args) throws URISyntaxException {
    final ClientExample client = new ClientExample(new URI("wss://ws.tradier.com/v1/markets/events"));
    client.connect();
  }
}

class ClientExample extends WebSocketClient {

  public ClientExample(URI serverURI) {
    super(serverURI);
  }

  @Override
  public void onOpen(ServerHandshake handshakedata) {
  System.out.println("opened connection");
  send("{" +
       "\"symbols\": [\"SPY\"], " +
				"\"filter\": [\"trade\"], " +
        "\"sessionid\": \"SESSION_ID\", " +
        "\"linebreak\": true" +
      "}");
  }

  @Override
  public void onMessage(String message) {
    System.out.println("Received: " + message);
  }

  @Override
  public void onClose(int code, String reason, boolean remote) {
    System.out.println("Connection closed by " + (remote ? "remote peer" : "us") + " Code: " + code + " Reason: " + reason);
  }

  @Override
  public void onError(Exception e) {
    System.err.println("Exception: " + e.getMessage());
  }
}
```

```ruby
require 'faye/websocket'
require 'eventmachine'

EM.run do
  ws = Faye::WebSocket::Client.new('wss://ws.tradier.com/v1/markets/events')

  ws.on :open do |event|
    puts :open
    ws.send('{"symbols": ["SPY"], "filter": ["trade"], "sessionid": "SESSION_ID", "linebreak": true}')
  end

  ws.on :message do |event|
    puts event.data
  end

  ws.on :close do |event|
    puts :close, event.code, event.reason
    ws = nil
  end
end
```

### Response Example

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