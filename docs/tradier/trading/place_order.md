Place Order

# Place Order

Place a trading order. Supports equity, option, multileg, combo, OTO, OCO, and OTOCO order types.

For more information on all order types, including requirements and constraints, please see our guides on trading.

<br />

## Advanced Orders

### Combo Orders:

Place a combo order. This is a specialized type of order consisting of one equity leg and one option leg. It can optionally include a second option leg, for some strategies.

<br />

### OCO Orders:

Place a one-cancels-other order. This order type is composed of two separate orders sent simultaneously. The property keys of each order are indexed.

Please note these specific validations:

* type must be different for both legs.
* If both orders are equities, the symbol must be the same.
* If both orders are options, the option\_symbol must be the same.
* If sending duration per leg, both orders must have the same duration.

<br />

### OTO Orders:

Place a one-triggers-other order. This order type is composed of two separate orders sent simultaneously. The property keys of each order are indexed.

<br />

### OTOCO Orders:

Place a one-triggers-one-cancels-other order. This order type is composed of three separate orders sent simultaneously. The property keys of each order are indexed.

Please note these specific validations:

* If all equity orders, second and third orders must have the same symbol.
* If all option orders, second and third orders must have the same option\_symbol.
* Only the first leg of an OTOCO can have a Market order type.
* Second and third orders must always have a different type.
* If sending duration per leg, second and third orders must have the same duration.

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
    "/v1/accounts/{account_id}/orders": {
      "post": {
        "tags": [
          "Trading"
        ],
        "summary": "Place Order",
        "description": "Place a trading order. Supports equity, option, multileg, combo, OTO, OCO, and OTOCO order types.",
        "operationId": "brokerage-api-trading-place-order",
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
                "oneOf": [
                  {
                    "$ref": "#/components/schemas/EquityOrderRequest"
                  },
                  {
                    "$ref": "#/components/schemas/OptionOrderRequest"
                  },
                  {
                    "$ref": "#/components/schemas/MultilegOrderRequest"
                  },
                  {
                    "$ref": "#/components/schemas/ComboOrderRequest"
                  },
                  {
                    "$ref": "#/components/schemas/OTOOrderRequest"
                  },
                  {
                    "$ref": "#/components/schemas/OCOOrderRequest"
                  },
                  {
                    "$ref": "#/components/schemas/OTOCOOrderRequest"
                  }
                ],
                "discriminator": {
                  "propertyName": "class",
                  "mapping": {
                    "equity": "#/components/schemas/EquityOrderRequest",
                    "option": "#/components/schemas/OptionOrderRequest",
                    "multileg": "#/components/schemas/MultilegOrderRequest",
                    "combo": "#/components/schemas/ComboOrderRequest",
                    "oto": "#/components/schemas/OTOOrderRequest",
                    "oco": "#/components/schemas/OCOOrderRequest",
                    "otoco": "#/components/schemas/OTOCOOrderRequest"
                  }
                }
              },
              "examples": {
                "equityOrder": {
                  "summary": "Equity Order",
                  "value": {
                    "class": "equity",
                    "symbol": "AAPL",
                    "side": "buy",
                    "quantity": 10,
                    "type": "market",
                    "duration": "day"
                  }
                },
                "optionOrder": {
                  "summary": "Option Order",
                  "value": {
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
      "EquityOrderRequest": {
        "allOf": [
          {
            "$ref": "#/components/schemas/BaseOrderRequest"
          },
          {
            "type": "object",
            "required": [
              "class"
            ],
            "properties": {
              "class": {
                "type": "string",
                "enum": [
                  "equity"
                ],
                "description": "Order class identifier"
              },
              "side": {
                "type": "string",
                "enum": [
                  "buy",
                  "sell",
                  "sell_short",
                  "buy_to_cover"
                ],
                "description": "The side of the order. One of: buy, sell, sell_short, buy_to_cover"
              }
            }
          }
        ]
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
      },
      "MultilegOrderRequest": {
        "type": "object",
        "required": [
          "class",
          "symbol",
          "type",
          "duration",
          "preview"
        ],
        "properties": {
          "class": {
            "type": "string",
            "enum": [
              "multileg"
            ],
            "description": "Order class identifier"
          },
          "symbol": {
            "type": "string",
            "description": "The underlying security symbol of the options"
          },
          "type": {
            "type": "string",
            "enum": [
              "market",
              "debit",
              "credit",
              "even"
            ],
            "description": "The type of order to be placed. One of: market, debit, credit, even"
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
              "buy_to_open",
              "buy_to_close",
              "sell_to_open",
              "sell_to_close"
            ],
            "description": "The side of the option leg. One of: buy_to_open, buy_to_close, sell_to_open, sell_to_close"
          },
          "quantity[0]": {
            "type": "number",
            "format": "string",
            "description": "The number of contracts for the option leg"
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
          "option_symbol[3]": {
            "type": "string",
            "items": {
              "type": "string"
            },
            "description": "OCC option symbol of the option"
          },
          "side[3]": {
            "type": "string",
            "enum": [
              "buy_to_open",
              "buy_to_close",
              "sell_to_open",
              "sell_to_close"
            ],
            "description": "The side of the option leg. One of: buy_to_open, buy_to_close, sell_to_open, sell_to_close"
          },
          "quantity[3]": {
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
      },
      "OTOOrderRequest": {
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
              "oto"
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
            "description": "Time the order will remain active. One of: day, gtc, pre, post. For different durations per leg, duration can be specified as 0 indexed positions, ie duration[0]=day&duration[1]=gtc"
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
              "market",
              "limit",
              "stop",
              "stop_limit"
            ],
            "description": "The type of order to be placed. Second order, one of: market,limit, stop, stop_limit"
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
      },
      "OTOCOOrderRequest": {
        "type": "object",
        "required": [
          "class",
          "quantity[0]",
          "type[0]",
          "side[0]",
          "quantity[1]",
          "type[1]",
          "side[1]",
          "quantity[2]",
          "type[2]",
          "side[2]",
          "preview"
        ],
        "properties": {
          "class": {
            "type": "string",
            "enum": [
              "otoco"
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
            "description": "Time the order will remain active. One of: day, gtc, pre, post. Alternatively, it can also be sent per leg (duration[index]) as long as the main duration is omitted."
          },
          "symbol[0]": {
            "type": "string",
            "items": {
              "type": "string"
            },
            "description": "The underlying security symbol, use for equities legs"
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
            "description": "OCC option symbol of the option, use for option legs"
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
            "description": "The underlying security symbol, use for equities legs"
          },
          "option_symbol[1]": {
            "type": "string",
            "items": {
              "type": "string"
            },
            "description": "OCC option symbol of the option"
          },
          "quantity[1]": {
            "type": "number",
            "format": "string",
            "description": "The number of contracts for the option leg"
          },
          "type[1]": {
            "type": "string",
            "enum": [
              "market",
              "limit",
              "stop",
              "stop_limit"
            ],
            "description": "The type of order to be placed. Second order, one of: limit, stop, stop_limit"
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
          "symbol[2]": {
            "type": "string",
            "description": "The underlying security symbol, use for equities legs"
          },
          "option_symbol[2]": {
            "type": "string",
            "items": {
              "type": "string"
            },
            "description": "OCC option symbol of the option, use for option legs"
          },
          "quantity[2]": {
            "type": "number",
            "format": "string",
            "description": "The number of contracts for the option leg"
          },
          "type[2]": {
            "type": "string",
            "enum": [
              "limit",
              "stop",
              "stop_limit"
            ],
            "description": "The type of order to be placed. Second order, one of: limit, stop, stop_limit"
          },
          "side[2]": {
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
          "price[2]": {
            "type": "number",
            "format": "string",
            "description": "Limit price. Required only for limit, stop_limit, debit and credit orders."
          },
          "stop[2]": {
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