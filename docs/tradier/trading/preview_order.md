Previewing an Order

# Previewing an Order

Previewing an order provides insight into validation and cost an order might have on an account. We recommend most developers and platforms leverage previews before placing orders.

When previewing an order, all order validation rules are run, including buying power checks. All applicable fees and commissions are delivered in the response. Submit the order with all necessary parameters and include the additional parameter of preview=true

### Response

```
{
  "order": {
    "status": "ok",
    "commission": 3.49000000,
    "cost": 34.715100000000,
    "fees": 0,
    "symbol": "T",
    "quantity": 1,
    "side": "buy",
    "type": "market",
    "duration": "day",
    "result": true,
    "order_cost": 31.225100000000,
    "margin_change": 0,
    "request_date": "2019-05-14T15:56:47.371",
    "extended_hours": false,
    "class": "equity",
    "strategy": "equity",
    "day_trades": 3
  }
}
```