Get Options Chains

# Get Options Chains

Get option chains for a specific underlying symbol and expiration date. Greek and IV data is included courtesy of ORATS. Please check out their APIs for more in-depth options data.

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
    "/v1/markets/options/chains": {
      "get": {
        "tags": [
          "Markets"
        ],
        "summary": "Get Options Chains",
        "description": "Get option chains for a specific underlying symbol and expiration date. Greek and IV data is included courtesy of ORATS. Please check out their APIs for more in-depth options data.",
        "operationId": "brokerage-api-markets-get-options-chains",
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
            "name": "symbol",
            "in": "query",
            "required": true,
            "schema": {
              "type": "string"
            },
            "description": "The underlying security symbol",
            "example": "AAPL"
          },
          {
            "name": "expiration",
            "in": "query",
            "required": true,
            "schema": {
              "type": "string",
              "format": "date"
            },
            "description": "The expiration date (YYYY-MM-DD)",
            "example": "2021-04-16"
          },
          {
            "name": "greeks",
            "in": "query",
            "required": false,
            "schema": {
              "type": "boolean",
              "default": false
            },
            "description": "Include greek calculations"
          }
        ],
        "responses": {
          "200": {
            "description": "Options chains information",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/OptionsChainResponse"
                },
                "example": {
                  "options": {
                    "option": [
                      {
                        "symbol": "AAPL210416C00125000",
                        "description": "AAPL Apr 16 2021 $125.00 Call",
                        "exch": "Z",
                        "type": "option",
                        "last": 3.45,
                        "change": 0.3,
                        "volume": 1105,
                        "open": 3.25,
                        "high": 3.5,
                        "low": 3.25,
                        "close": 3.15,
                        "bid": 3.4,
                        "ask": 3.45,
                        "underlying": "AAPL",
                        "strike": 125,
                        "change_percentage": 9.52,
                        "average_volume": 1120,
                        "last_volume": 10,
                        "trade_date": 1612196262,
                        "prevclose": 3.15,
                        "week_52_high": 5,
                        "week_52_low": 0.75,
                        "bidsize": 36,
                        "bidexch": "P",
                        "bid_date": 1612196200,
                        "asksize": 75,
                        "askexch": "P",
                        "ask_date": 1612196200,
                        "open_interest": 8249,
                        "contract_size": 100,
                        "expiration_date": "2021-04-16",
                        "expiration_type": "standard",
                        "option_type": "call",
                        "root_symbol": "AAPL"
                      }
                    ]
                  }
                }
              }
            }
          },
          "400": {
            "$ref": "#/components/responses/BadRequest"
          },
          "401": {
            "$ref": "#/components/responses/Unauthorized"
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
    "responses": {
      "Unauthorized": {
        "description": "Authentication required or invalid credentials"
      },
      "BadRequest": {
        "description": "Invalid request parameters or body"
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
      },
      "OptionsChainResponse": {
        "type": "object",
        "properties": {
          "options": {
            "type": "object",
            "properties": {
              "option": {
                "type": "array",
                "items": {
                  "$ref": "#/components/schemas/Quote"
                }
              }
            }
          }
        }
      }
    }
  }
}
```