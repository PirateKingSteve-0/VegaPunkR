Place Combo Order

# Place Combo Order

Place a combo order consisting of one equity leg and one or two option legs. Send to `POST /v1/accounts/{account_id}/orders` with `class=combo`.

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
    "/v1/accounts/{account_id}/orders/combo": {
      "post": {
        "tags": [
          "Trading"
        ],
        "summary": "Place Combo Order",
        "description": "Place a combo order consisting of one equity leg and one or two option legs. Send to `POST /v1/accounts/{account_id}/orders` with `class=combo`.",
        "operationId": "brokerage-api-trading-place-combo-order",
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
                "$ref": "#/components/schemas/ComboOrderRequest"
              },
              "example": {
                "class": "combo",
                "symbol": "AAPL",
                "type": "debit",
                "duration": "day",
                "price": 2,
                "side[0]": "buy",
                "quantity[0]": 100,
                "option_symbol[1]": "AAPL210416C00125000",
                "side[1]": "sell_to_open",
                "quantity[1]": 1
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
      "ComboOrderRequest": {
        "type": "object",
        "required": [
          "class",
          "symbol",
          "type",
          "duration",
          "side[0]",
          "quantity[0]",
          "option_symbol[1]",
          "side[1]",
          "quantity[1]",
          "preview"
        ],
        "properties": {
          "class": {
            "type": "string",
            "enum": [
              "combo"
            ],
            "description": "Order class identifier"
          },
          "symbol": {
            "type": "string",
            "description": "The underlying security symbol"
          },
          "type": {
            "type": "string",
            "enum": [
              "market",
              "debit",
              "credit",
              "even"
            ],
            "description": "The order type"
          },
          "duration": {
            "type": "string",
            "enum": [
              "day",
              "gtc",
              "pre",
              "post"
            ],
            "description": "The order duration"
          },
          "price": {
            "type": "number",
            "format": "string",
            "description": "The limit price (required for debit and credit orders)"
          },
          "side[0]": {
            "type": "string",
            "enum": [
              "buy",
              "buy_to_cover",
              "sell",
              "sell_short"
            ],
            "description": "The side of the equity leg. One of: buy, buy_to_cover, sell, sell_short"
          },
          "quantity[0]": {
            "type": "number",
            "format": "string",
            "description": "The quantity of shares for the equity leg"
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
              "buy_to_open",
              "buy_to_close",
              "sell_to_open",
              "sell_to_close"
            ],
            "description": "The side of the option leg. One of: buy_to_open, buy_to_close, sell_to_open, sell_to_close"
          },
          "quantity[1]": {
            "type": "number",
            "format": "string",
            "description": "The number of contracts for the option leg"
          },
          "option_symbol[2]": {
            "type": "string",
            "items": {
              "type": "string"
            },
            "description": "OCC option symbol of the option"
          },
          "side[2]": {
            "type": "string",
            "enum": [
              "buy_to_open",
              "buy_to_close",
              "sell_to_open",
              "sell_to_close"
            ],
            "description": "The side of the option leg. One of: buy_to_open, buy_to_close, sell_to_open, sell_to_close"
          },
          "quantity[2]": {
            "type": "number",
            "format": "string",
            "description": "The number of contracts for the option leg"
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