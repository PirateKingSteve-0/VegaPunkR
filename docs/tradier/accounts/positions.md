Get Account Positions

# Get Account Positions

Get the current positions being held in an account

When getting positions for an account, multiple positions will be returned as an array of objects and multiple positions of the same symbol will grouped into a single object. If one a single position exists in the account at the time of the call then only the position will be returned as a singe object, not nested in an array.

# Credentials

BEARER BEARER<ACCESS_TOKEN>

# URL

## Live server
https://api.tradier.com/v1/accounts/{account_id}/positions

## Sandbox
https://sandbox.tradier.com/v1/accounts/{account_id}/positions


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
    "/v1/accounts/{account_id}/positions": {
      "get": {
        "tags": [
          "Accounts"
        ],
        "summary": "Get Account Positions",
        "description": "Get the current positions being held in an account",
        "operationId": "brokerage-api-accounts-get-account-positions",
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
            "description": "Account positions information",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/PositionsResponse"
                },
                "example": {
                  "positions": {
                    "position": [
                      {
                        "cost_basis": 7954.16,
                        "date_acquired": "2015-01-01T15:25:47.230Z",
                        "id": 40,
                        "quantity": 37,
                        "symbol": "AAPL"
                      },
                      {
                        "cost_basis": 82.75,
                        "date_acquired": "2014-09-01T15:25:47.230Z",
                        "id": 41,
                        "quantity": -2,
                        "symbol": "NFLX"
                      }
                    ]
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
      "Position": {
        "type": "object",
        "properties": {
          "cost_basis": {
            "type": "number",
            "format": "float",
            "description": "The cost basis of the position"
          },
          "date_acquired": {
            "type": "string",
            "format": "date-time",
            "description": "The date the position was acquired"
          },
          "id": {
            "type": "integer",
            "description": "The position ID"
          },
          "quantity": {
            "type": "number",
            "format": "float",
            "description": "The quantity of the security (negative for short positions)"
          },
          "symbol": {
            "type": "string",
            "description": "The security symbol"
          }
        }
      },
      "PositionsResponse": {
        "type": "object",
        "properties": {
          "positions": {
            "type": "object",
            "properties": {
              "position": {
                "type": "array",
                "items": {
                  "$ref": "#/components/schemas/Position"
                },
                "description": "List of positions held in the account"
              }
            }
          }
        }
      }
    }
  }
}
```