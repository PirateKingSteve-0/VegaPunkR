Websocket Account Data Streaming

# Websocket Account Data Streaming

Note: This API is presently in Beta. It is only available to Tradier Brokerage account holders and should only be used in production applications with caution.

Stream account updates using WebSocket streaming. You will receive a different payload depending on the account event that occurred. Details about each event can be found in the response definition. You can continually update the data in your stream by resending this request with different parameters.

Note: In order to stream data, you must first create a streaming session. Upon receiving a sessionid, you will have up to 5 minutes to connect to a streaming endpoint before the session expires.

Once connected and streaming data, to make modifications to your current streaming connection, simply resend your request payload using the existing sessionid. Note: if your sessionid has expired, you will need to get a new one and send it with your adjusted payload.

While we do not publish the symbol limits for these APIs, we do monitor for abuse to make sure people aren’t doing anything egregious (like asking for an entire exchange worth of symbols). Essentially, ask for what you need. Don’t abuse the APIs and you should be fine. It is not permitted to open more than one session at a time.

Note that WebSocket streaming uses a different endpoint: wss\://ws.tradier.com

```
wss://ws.tradier.com/v1/accounts/events
```

If you're developing using a paper trading account, change the hostname to wss\://sandbox-ws.tradier.com

<br />

### Parameters

| Parameter       | Type | Param Type | Required | Values/Example                | Default |
| --------------- | ---- | ---------- | -------- | ----------------------------- | ------- |
| events          | JSON | Array      | Yes      | \["order"]                    | N/A     |
| sessionid       | JSON | String     | Yes      | "9D1C7018CFEB6F8ECF8CAA58B33" | N/A     |
| excludeAccounts | JSON | Array      | No       | \["6YA00001", "6YA00002"]     | N/A     |

<br />

### Code Examples

```python
import asyncio
import websockets

async def connect_and_consume():
  uri = "wss://ws.tradier.com/v1/accounts/events"
  async with websockets.connect(uri) as websocket:
    payload = '{"events": ["order"], "sessionid": "SESSION_ID", "excludeAccounts": []}'

    await websocket.send(payload)
    print(f"> {payload}")

    while True:
      response = await websocket.recv()
      print(f"< {response}")

asyncio.get_event_loop().run_until_complete(connect_and_consume())
```

```node
const WebSocket = require('ws');
const ws = new WebSocket('wss://ws.tradier.com/v1/accounts/events');

ws.on('open', function open() {
  console.log('Connected, sending subscription commands...');
  ws.send('{"events": ["order"], "sessionid": "SESSION_ID", "excludeAccounts": []}');
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
    final ClientExample client = new ClientExample(new URI("wss://ws.tradier.com/v1/accounts/events"));
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
        "\"events\": [\"order\"], " +
        "\"sessionid\": \"SESSION_ID\", " +
        "\"excludeAccounts\": []" +
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
  ws = Faye::WebSocket::Client.new('wss://ws.tradier.com/v1/accounts/events')
    
  ws.on :open do |event|
    puts :open
    ws.send('{"events": ["order"], "sessionid": "SESSION_ID", "excludeAccounts": []}')
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

### Return Examples

```
{
   "id":1107075,
   "event":"order",
   "status":"open",
   "type": "limit",
   "price":10.0,
   "stop_price":0.0,
   "avg_fill_price":0.0,
   "executed_quantity":0.0,
   "last_fill_quantity":0.0,
   "remaining_quantity":2.0,
   "transaction_date":"2021-08-09T20:05:35.277Z",
   "create_date":"2021-08-09T20:05:35.277Z",
   "account":"6YA"
}
{
   "id":1107075,
   "event":"order",
   "status":"pending",
   "type": "limit",
   "price":10.0,
   "stop_price":0.0,
   "avg_fill_price":0.0,
   "executed_quantity":0.0,
   "last_fill_quantity":0.0,
   "remaining_quantity":2.0,
   "transaction_date":"2021-08-09T20:05:35.277Z",
   "create_date":"2021-08-09T20:05:35.277Z",
   "account":"6YA"
}
{
   "id":1107075,
   "event":"order",
   "status":"filled",
   "type": "limit",
   "price":10.0,
   "stop_price":0.0,
   "avg_fill_price":10.0,
   "executed_quantity":2.0,
   "last_fill_quantity":0.0,
   "remaining_quantity":0.0,
   "transaction_date":"2021-08-09T20:05:35.277Z",
   "create_date":"2021-08-09T20:05:35.277Z",
   "account":"6YA"
}
```