Place Option Order

# Place Option Order

Place a single-leg option order. Send to `POST /v1/accounts/{account_id}/orders` with `class=option`.

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
    "/v1/accounts/{account_id}/orders/option": {
      "post": {
        "tags": [
          "Trading"
        ],
        "summary": "Place Option Order",
        "description": "Place a single-leg option order. Send to `POST /v1/accounts/{account_id}/orders` with `class=option`.",
        "operationId": "brokerage-api-trading-place-option-order",
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
                "$ref": "#/components/schemas/OptionOrderRequest"
              },
              "example": {
                "class": "option",
                "symbol": "AAPL",
                "option_symbol": "AAPL210416C00125000",
                "side": "buy_to_open",
                "quantity": 1,
                "type": "limit",
                "duration": "day",
                "price": 3.5
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
      "BaseOrderRequest": {
        "type": "object",
        "required": [
          "class",
          "symbol",
          "option_symbol",
          "quantity",
          "type",
          "duration",
          "preview"
        ],
        "properties": {
          "symbol": {
            "type": "string",
            "description": "The security symbol or underlying symbol for options"
          },
          "quantity": {
            "type": "number",
            "format": "string",
            "description": "The order quantity"
          },
          "type": {
            "type": "string",
            "enum": [
              "market",
              "limit",
              "stop",
              "stop_limit"
            ],
            "description": "The type of order to be placed. One of: market, limit, stop, stop_limit"
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
            "description": "The limit price (required for limit and stop_limit orders)"
          },
          "stop": {
            "type": "number",
            "format": "string",
            "description": "The stop price (required for stop and stop_limit orders)"
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
      },
      "OptionOrderRequest": {
        "allOf": [
          {
            "$ref": "#/components/schemas/BaseOrderRequest"
          },
          {
            "type": "object",
            "required": [
              "class",
              "option_symbol"
            ],
            "properties": {
              "class": {
                "type": "string",
                "enum": [
                  "option"
                ],
                "description": "Order class identifier"
              },
              "option_symbol": {
                "type": "string",
                "description": "The OCC option symbol"
              },
              "side": {
                "type": "string",
                "enum": [
                  "buy_to_open",
                  "sell_to_open",
                  "sell_to_close",
                  "buy_to_close"
                ],
                "description": "The side of the order. One of: buy_to_open, buy_to_close, sell_to_open, sell_to_close"
              }
            }
          }
        ]
      }
    }
  }
}
```