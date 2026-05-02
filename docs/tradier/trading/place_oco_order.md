Place OCO Order

# Place OCO Order

Place a one-cancels-other (OCO) order composed of two simultaneous orders. If one executes, the other is automatically canceled. Send to `POST /v1/accounts/{account_id}/orders` with `class=oco`.

**Validations:**
- `type` must be different for both legs.
- If both orders are equities, the `symbol` must be the same.
- If both orders are options, the `option_symbol` must be the same.
- If sending `duration` per leg, both orders must have the same duration.

# OpenAPI definition

```json
{
  "openapi": "3.0.0",
  "info": {
    "title": "Tradier Brokerage API",
    "description": "API for accessing Tradier brokerage services",
    "version": "1.0.0"
  },
  "servers": [
    {
      "url": "https://api.tradier.com",
      "description": "Production server"
    },
    {
      "url": "https://sandbox.tradier.com",
      "description": "Sandbox environment for testing"
    }
  ],
  "paths": {
    "/v1/accounts/{account_id}/orders/oco": {
      "post": {
        "tags": [
          "Trading"
        ],
        "summary": "Place OCO Order",
        "description": "Place a one-cancels-other (OCO) order composed of two simultaneous orders. If one executes, the other is automatically canceled. Send to `POST /v1/accounts/{account_id}/orders` with `class=oco`.\n\n**Validations:**\n- `type` must be different for both legs.\n- If both orders are equities, the `symbol` must be the same.\n- If both orders are options, the `option_symbol` must be the same.\n- If sending `duration` per leg, both orders must have the same duration.",
        "operationId": "brokerage-api-trading-place-oco-order",
        "security": [
          {
            "BearerAuth": []
          }
        ],
        "parameters": [
          {
            "$ref": "#/components/parameters/AccountIdParam"
          },
          {
            "$ref": "#/components/parameters/ContentTypeHeader"
          }
        ],
        "requestBody": {
          "required": true,
          "content": {
            "application/x-www-form-urlencoded": {
              "schema": {
                "$ref": "#/components/schemas/OCOOrderRequest"
              },
              "example": {
                "class": "oco",
                "duration": "gtc",
                "symbol[0]": "AAPL",
                "quantity[0]": 10,
                "type[0]": "limit",
                "side[0]": "sell",
                "price[0]": 150,
                "symbol[1]": "AAPL",
                "quantity[1]": 10,
                "type[1]": "stop",
                "side[1]": "sell",
                "stop[1]": 120
              }
            }
          }
        },
        "responses": {
          "200": {
            "$ref": "#/components/responses/OrderResponse"
          },
          "400": {
            "$ref": "#/components/responses/BadRequest"
          },
          "401": {
            "$ref": "#/components/responses/Unauthorized"
          },
          "403": {
            "$ref": "#/components/responses/Forbidden"
          },
          "404": {
            "$ref": "#/components/responses/NotFound"
          }
        }
      }
    }
  },
  "components": {
    "parameters": {
      "ContentTypeHeader": {
        "name": "Content-Type",
        "in": "header",
        "required": true,
        "schema": {
          "type": "string",
          "enum": [
            "application/x-www-form-urlencoded"
          ]
        },
        "description": "Request content type"
      },
      "AccountIdParam": {
        "name": "account_id",
        "in": "path",
        "required": true,
        "schema": {
          "type": "string"
        },
        "description": "ID of the account",
        "example": "VA000001"
      }
    },
    "responses": {
      "Unauthorized": {
        "description": "Authentication required or invalid credentials"
      },
      "Forbidden": {
        "description": "Access denied to the requested resource"
      },
      "NotFound": {
        "description": "The requested resource was not found"
      },
      "BadRequest": {
        "description": "Invalid request parameters or body"
      },
      "OrderResponse": {
        "description": "Order response information",
        "content": {
          "application/json": {
            "schema": {
              "type": "object",
              "properties": {
                "order": {
                  "$ref": "#/components/schemas/DetailedOrder"
                }
              }
            },
            "example": {
              "order": {
                "id": 123456,
                "status": "ok",
                "partner_id": "partner_12345"
              }
            }
          }
        }
      }
    },
    "securitySchemes": {
      "BearerAuth": {
        "type": "http",
        "scheme": "bearer",
        "bearerFormat": "Bearer <access_token>",
        "description": "Authentication using Bearer token"
      }
    },
    "schemas": {
      "Order": {
        "type": "object",
        "properties": {
          "id": {
            "type": "integer",
            "description": "The order ID"
          },
          "type": {
            "type": "string",
            "description": "The order type",
            "enum": [
              "market",
              "limit",
              "stop",
              "stop_limit",
              "debit",
              "credit",
              "even"
            ]
          },
          "symbol": {
            "type": "string",
            "description": "The security symbol"
          },
          "side": {
            "type": "string",
            "description": "The side of the order",
            "enum": [
              "buy",
              "buy_to_cover",
              "sell",
              "sell_short",
              "buy_to_open",
              "buy_to_close",
              "sell_to_open",
              "sell_to_close"
            ]
          },
          "quantity": {
            "type": "number",
            "format": "float",
            "description": "The order quantity"
          },
          "status": {
            "type": "string",
            "description": "The order status",
            "enum": [
              "pending",
              "open",
              "partially_filled",
              "filled",
              "expired",
              "canceled",
              "rejected",
              "pending_cancel"
            ]
          },
          "duration": {
            "type": "string",
            "description": "The order duration",
            "enum": [
              "day",
              "gtc",
              "pre",
              "post"
            ]
          },
          "avg_fill_price": {
            "type": "number",
            "format": "float",
            "description": "The average fill price"
          },
          "exec_quantity": {
            "type": "number",
            "format": "float",
            "description": "The executed quantity"
          },
          "create_date": {
            "type": "string",
            "format": "date-time",
            "description": "The date the order was created"
          },
          "transaction_date": {
            "type": "string",
            "format": "date-time",
            "description": "The date of the last transaction"
          },
          "class": {
            "type": "string",
            "description": "The security class",
            "enum": [
              "equity",
              "option",
              "multileg",
              "combo"
            ]
          }
        }
      },
      "DetailedOrder": {
        "allOf": [
          {
            "$ref": "#/components/schemas/Order"
          },
          {
            "type": "object",
            "properties": {
              "last_fill_price": {
                "type": "number",
                "format": "float",
                "description": "The price of the last fill"
              },
              "last_fill_quantity": {
                "type": "number",
                "format": "float",
                "description": "The quantity of the last fill"
              },
              "remaining_quantity": {
                "type": "number",
                "format": "float",
                "description": "The quantity remaining to be filled"
              }
            }
          }
        ]
      },
      "OCOOrderRequest": {
        "type": "object",
        "required": [
          "class",
          "duration",
          "symbol[0]",
          "quantity[0]",
          "type[0]",
          "side[0]",
          "symbol[1]",
          "quantity[1]",
          "type[1]",
          "side[1]",
          "preview"
        ],
        "properties": {
          "class": {
            "type": "string",
            "enum": [
              "oco"
            ],
            "description": "Order class identifier"
          },
          "duration": {
            "type": "string",
            "enum": [
              "day",
              "gtc",
              "pre",
              "post"
            ],
            "description": "Time the order will remain active. One of: day, gtc, pre, post."
          },
          "symbol[0]": {
            "type": "string",
            "description": "The underlying security symbol"
          },
          "quantity[0]": {
            "type": "number",
            "format": "string",
            "description": "The number of contracts for the option leg"
          },
          "type[0]": {
            "type": "string",
            "enum": [
              "limit",
              "stop",
              "stop_limit"
            ],
            "description": "The type of order to be placed. First order, one of: limit, stop, stop_limit"
          },
          "option_symbol[0]": {
            "type": "string",
            "items": {
              "type": "string"
            },
            "description": "OCC option symbol of the option"
          },
          "side[0]": {
            "type": "string",
            "enum": [
              "buy",
              "buy_to_cover",
              "sell",
              "sell_short",
              "buy_to_open",
              "buy_to_close",
              "sell_to_open",
              "sell_to_close"
            ],
            "description": "The side of the leg. Equity orders, one of: buy, buy_to_cover, sell, sell_short Option orders, one of: buy_to_open, buy_to_close, sell_to_open, sell_to_close"
          },
          "price[0]": {
            "type": "number",
            "format": "string",
            "description": "Limit price. Required only for limit, stop_limit, debit and credit orders."
          },
          "stop[0]": {
            "type": "number",
            "format": "string",
            "description": "Stop price. Required only for stop and stop_limit orders."
          },
          "symbol[1]": {
            "type": "string",
            "description": "The underlying security symbol"
          },
          "quantity[1]": {
            "type": "number",
            "format": "string",
            "description": "The number of contracts for the option leg"
          },
          "type[1]": {
            "type": "string",
            "enum": [
              "limit",
              "stop",
              "stop_limit"
            ],
            "description": "The type of order to be placed. Second order, one of: limit, stop, stop_limit"
          },
          "option_symbol[1]": {
            "type": "string",
            "items": {
              "type": "string"
            },
            "description": "OCC option symbol of the option"
          },
          "side[1]": {
            "type": "string",
            "enum": [
              "buy",
              "buy_to_cover",
              "sell",
              "sell_short",
              "buy_to_open",
              "buy_to_close",
              "sell_to_open",
              "sell_to_close"
            ],
            "description": "The side of the leg. Equity orders, one of: buy, buy_to_cover, sell, sell_short Option orders, one of: buy_to_open, buy_to_close, sell_to_open, sell_to_close"
          },
          "price[1]": {
            "type": "number",
            "format": "string",
            "description": "Limit price. Required only for limit, stop_limit, debit and credit orders."
          },
          "stop[1]": {
            "type": "number",
            "format": "string",
            "description": "Stop price. Required only for stop and stop_limit orders."
          },
          "tag": {
            "type": "string",
            "description": "User-defined tag for the order"
          },
          "preview": {
            "type": "boolean",
            "description": "When true, validates the order without submitting it"
          }
        }
      }
    }
  }
}
```