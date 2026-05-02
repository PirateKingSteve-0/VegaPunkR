Get Account Balance

# Get Account Balance

Get the current account balance and margin information.

# Credentials

BEARER BEARER<ACCESS_TOKEN>

# URL

## Live server
https://api.tradier.com/v1/accounts/{account_id}/balances

## Sandbox
https://sandbox.tradier.com/v1/accounts/{account_id}/balances


# Requests (Example)
```python
import requests

url = "https://sandbox.tradier.com/v1/accounts/account_id/balances"

headers = {"Accept": "application/json"}

response = requests.get(url, headers=headers)

print(response.text)
```

## Response Example
```json
{
  "balance": {
    "balances": {
      "option_short_value": 0,
      "total_equity": 17798.36,
      "account_number": "VA00000000",
      "account_type": "margin",
      "close_pl": -4813,
      "current_requirement": 2557,
      "equity": 0,
      "long_market_value": 11434.5,
      "market_value": 11434.5,
      "open_pl": 546.9,
      "option_long_value": 8877.5,
      "option_requirement": 0,
      "pending_orders_count": 0,
      "short_market_value": 0,
      "stock_long_value": 2557,
      "total_cash": 6363.86,
      "uncleared_funds": 0,
      "pending_cash": 0
    },
    "margin": {
      "fed_call": 0,
      "maintenance_call": 0,
      "option_buying_power": 6363.86,
      "stock_buying_power": 12727.72,
      "stock_short_value": 0,
      "sweep": 0
    },
    "cash": {
      "cash_available": 4343.38,
      "sweep": 0,
      "unsettled_funds": 1310
    },
    "pdt": {
      "fed_call": 0,
      "maintenance_call": 0,
      "option_buying_power": 6363.86,
      "stock_buying_power": 12727.72,
      "stock_short_value": 0
    }
  }
}
```

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
    "/v1/accounts/{account_id}/balances": {
      "get": {
        "tags": [
          "Accounts"
        ],
        "summary": "Get Account Balance",
        "description": "Get the current account balance and margin information.",
        "operationId": "brokerage-api-accounts-get-account-balance",
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
            "$ref": "#/components/parameters/AcceptHeader"
          }
        ],
        "responses": {
          "200": {
            "description": "Account balance information",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/BalanceResponse"
                },
                "example": {
                  "balance": {
                    "balances": {
                      "option_short_value": 0,
                      "total_equity": 17798.36,
                      "account_number": "VA00000000",
                      "account_type": "margin",
                      "close_pl": -4813,
                      "current_requirement": 2557,
                      "equity": 0,
                      "long_market_value": 11434.5,
                      "market_value": 11434.5,
                      "open_pl": 546.9,
                      "option_long_value": 8877.5,
                      "option_requirement": 0,
                      "pending_orders_count": 0,
                      "short_market_value": 0,
                      "stock_long_value": 2557,
                      "total_cash": 6363.86,
                      "uncleared_funds": 0,
                      "pending_cash": 0
                    },
                    "margin": {
                      "fed_call": 0,
                      "maintenance_call": 0,
                      "option_buying_power": 6363.86,
                      "stock_buying_power": 12727.72,
                      "stock_short_value": 0,
                      "sweep": 0
                    },
                    "cash": {
                      "cash_available": 4343.38,
                      "sweep": 0,
                      "unsettled_funds": 1310
                    },
                    "pdt": {
                      "fed_call": 0,
                      "maintenance_call": 0,
                      "option_buying_power": 6363.86,
                      "stock_buying_power": 12727.72,
                      "stock_short_value": 0
                    }
                  }
                }
              }
            }
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
      "BalanceResponse": {
        "type": "object",
        "properties": {
          "balances": {
            "type": "object",
            "properties": {
              "option_short_value": {
                "type": "number",
                "format": "float",
                "description": "The value of short option positions"
              },
              "total_equity": {
                "type": "number",
                "format": "float",
                "description": "The total account value"
              },
              "account_number": {
                "type": "string",
                "description": "The account number"
              },
              "account_type": {
                "type": "string",
                "description": "The type of account (margin, cash)",
                "enum": [
                  "margin",
                  "cash"
                ]
              },
              "close_pl": {
                "type": "number",
                "format": "float",
                "description": "The profit/loss from closed positions"
              },
              "current_requirement": {
                "type": "number",
                "format": "float",
                "description": "The current margin requirement"
              },
              "equity": {
                "type": "number",
                "format": "float",
                "description": "The equity value"
              },
              "long_market_value": {
                "type": "number",
                "format": "float",
                "description": "The value of long positions"
              },
              "market_value": {
                "type": "number",
                "format": "float",
                "description": "The total market value"
              },
              "open_pl": {
                "type": "number",
                "format": "float",
                "description": "The profit/loss from open positions"
              },
              "option_long_value": {
                "type": "number",
                "format": "float",
                "description": "The value of long option positions"
              },
              "option_requirement": {
                "type": "number",
                "format": "float",
                "description": "The options margin requirement"
              },
              "pending_orders_count": {
                "type": "integer",
                "description": "The number of pending orders"
              },
              "short_market_value": {
                "type": "number",
                "format": "float",
                "description": "The value of short positions"
              },
              "stock_long_value": {
                "type": "number",
                "format": "float",
                "description": "The value of long stock positions"
              },
              "total_cash": {
                "type": "number",
                "format": "float",
                "description": "The total cash value"
              },
              "uncleared_funds": {
                "type": "number",
                "format": "float",
                "description": "The amount of uncleared funds"
              },
              "pending_cash": {
                "type": "number",
                "format": "float",
                "description": "The amount of pending cash"
              },
              "margin": {
                "type": "object",
                "properties": {
                  "fed_call": {
                    "type": "number",
                    "format": "float",
                    "description": "Federal call amount"
                  },
                  "maintenance_call": {
                    "type": "number",
                    "format": "float",
                    "description": "Maintenance call amount"
                  },
                  "option_buying_power": {
                    "type": "number",
                    "format": "float",
                    "description": "The buying power for options"
                  },
                  "stock_buying_power": {
                    "type": "number",
                    "format": "float",
                    "description": "The buying power for stocks"
                  },
                  "stock_short_value": {
                    "type": "number",
                    "format": "float",
                    "description": "The value of short stock positions"
                  },
                  "sweep": {
                    "type": "number",
                    "format": "float",
                    "description": "Sweep amount"
                  }
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