Get Quotes

# Get Quotes

Get quotes for one or more symbols

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
    "/v1/markets/quotes": {
      "get": {
        "tags": [
          "Markets"
        ],
        "summary": "Get Quotes",
        "description": "Get quotes for one or more symbols",
        "operationId": "brokerage-api-markets-get-quotes",
        "security": [
          {
            "BearerAuth": []
          }
        ],
        "parameters": [
          {
            "$ref": "#/components/parameters/AcceptHeader"
          },
          {
            "name": "symbols",
            "in": "query",
            "required": true,
            "schema": {
              "type": "string"
            },
            "description": "A comma-separated list of symbols",
            "example": "AAPL,SPY"
          },
          {
            "name": "greeks",
            "in": "query",
            "required": false,
            "schema": {
              "type": "boolean",
              "default": false
            },
            "description": "Include greek calculations for options"
          },
          {
            "name": "includeLotSize",
            "in": "query",
            "required": false,
            "schema": {
              "type": "boolean",
              "default": false
            },
            "description": "Include lot size information"
          }
        ],
        "responses": {
          "200": {
            "description": "Quote information",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/QuotesResponse"
                },
                "example": {
                  "quotes": {
                    "quote": {
                      "symbol": "AAPL",
                      "description": "Apple Inc",
                      "exch": "Q",
                      "type": "stock",
                      "last": 273.47,
                      "change": -1.78,
                      "volume": 47994892,
                      "open": 275,
                      "high": 275.73,
                      "low": 271.7,
                      "close": 273.47,
                      "bid": 273.53,
                      "ask": 273.59,
                      "change_percentage": -0.65,
                      "average_volume": 50967638,
                      "last_volume": 0,
                      "trade_date": 1762982100011,
                      "prevclose": 275.25,
                      "week_52_high": 277.32,
                      "week_52_low": 169.2101,
                      "bidsize": 100,
                      "bidexch": "Z",
                      "bid_date": 1762982138000,
                      "asksize": 200,
                      "askexch": "Q",
                      "ask_date": 1762982257000,
                      "root_symbols": "AAPL",
                      "lot_size": 100
                    }
                  }
                }
              }
            }
          }
        }
      }
    }
  },
  "components": {
    "parameters": {
      "AcceptHeader": {
        "name": "Accept",
        "in": "header",
        "required": true,
        "schema": {
          "type": "string",
          "enum": [
            "application/json"
          ]
        },
        "description": "Response format"
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
      "QuotesResponse": {
        "type": "object",
        "properties": {
          "quotes": {
            "type": "object",
            "properties": {
              "quote": {
                "oneOf": [
                  {
                    "$ref": "#/components/schemas/Quote"
                  },
                  {
                    "type": "array",
                    "items": {
                      "$ref": "#/components/schemas/Quote"
                    }
                  }
                ]
              }
            }
          }
        }
      },
      "Quote": {
        "type": "object",
        "properties": {
          "symbol": {
            "type": "string",
            "description": "The security symbol"
          },
          "description": {
            "type": "string",
            "description": "The security description"
          },
          "exch": {
            "type": "string",
            "description": "The exchange code"
          },
          "type": {
            "type": "string",
            "description": "The security type"
          },
          "last": {
            "type": "number",
            "format": "float",
            "description": "The last price"
          },
          "change": {
            "type": "number",
            "format": "float",
            "description": "The change in price"
          },
          "volume": {
            "type": "integer",
            "description": "The trading volume"
          },
          "open": {
            "type": "number",
            "format": "float",
            "description": "The opening price"
          },
          "high": {
            "type": "number",
            "format": "float",
            "description": "The high price"
          },
          "low": {
            "type": "number",
            "format": "float",
            "description": "The low price"
          },
          "close": {
            "type": "number",
            "format": "float",
            "description": "The previous closing price"
          },
          "bid": {
            "type": "number",
            "format": "float",
            "description": "The bid price"
          },
          "ask": {
            "type": "number",
            "format": "float",
            "description": "The ask price"
          },
          "change_percentage": {
            "type": "number",
            "format": "float",
            "description": "The percentage change in price"
          },
          "average_volume": {
            "type": "integer",
            "description": "The average trading volume"
          },
          "last_volume": {
            "type": "integer",
            "description": "The volume of the last trade"
          },
          "trade_date": {
            "type": "integer",
            "format": "int64",
            "description": "The date of the last trade (Unix timestamp)"
          },
          "prevclose": {
            "type": "number",
            "format": "float",
            "description": "The previous day's closing price"
          },
          "week_52_high": {
            "type": "number",
            "format": "float",
            "description": "The 52-week high price"
          },
          "week_52_low": {
            "type": "number",
            "format": "float",
            "description": "The 52-week low price"
          },
          "bidsize": {
            "type": "integer",
            "description": "The size of the bid"
          },
          "bidexch": {
            "type": "string",
            "description": "The exchange code for the bid"
          },
          "bid_date": {
            "type": "integer",
            "format": "int64",
            "description": "The date of the bid (Unix timestamp)"
          },
          "asksize": {
            "type": "integer",
            "description": "The size of the ask"
          },
          "askexch": {
            "type": "string",
            "description": "The exchange code for the ask"
          },
          "ask_date": {
            "type": "integer",
            "format": "int64",
            "description": "The date of the ask (Unix timestamp)"
          },
          "open_interest": {
            "type": "integer",
            "description": "The open interest (for options)"
          },
          "contract_size": {
            "type": "integer",
            "description": "The contract size (for options)"
          },
          "expiration_date": {
            "type": "string",
            "format": "date",
            "description": "The expiration date (for options)"
          },
          "expiration_type": {
            "type": "string",
            "description": "The expiration type (for options)"
          },
          "option_type": {
            "type": "string",
            "enum": [
              "call",
              "put"
            ],
            "description": "The option type (for options)"
          },
          "root_symbol": {
            "type": "string",
            "description": "The root symbol (for options)"
          },
          "underlying": {
            "type": "string",
            "description": "The underlying symbol (for options)"
          },
          "strike": {
            "type": "number",
            "format": "float",
            "description": "The strike price (for options)"
          },
          "lot_size": {
            "type": "integer",
            "description": "The lot size"
          },
          "greeks": {
            "type": "object",
            "description": "Option greeks (available when greeks=true)",
            "properties": {
              "delta": {
                "type": "number",
                "format": "float"
              },
              "gamma": {
                "type": "number",
                "format": "float"
              },
              "theta": {
                "type": "number",
                "format": "float"
              },
              "vega": {
                "type": "number",
                "format": "float"
              },
              "rho": {
                "type": "number",
                "format": "float"
              },
              "phi": {
                "type": "number",
                "format": "float"
              },
              "bid_iv": {
                "type": "number",
                "format": "float"
              },
              "mid_iv": {
                "type": "number",
                "format": "float"
              },
              "ask_iv": {
                "type": "number",
                "format": "float"
              },
              "smv_vol": {
                "type": "number",
                "format": "float"
              },
              "updated_at": {
                "type": "string",
                "format": "date-time"
              }
            }
          }
        }
      }
    }
  }
}
```