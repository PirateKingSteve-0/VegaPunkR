Get ETB Securities

# Get ETB Securities

The ETB list contains securities that are able to be sold short with a Tradier Brokerage account. The list is quite comprehensive and can result in a long download response time.

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
    "/v1/markets/etb": {
      "get": {
        "tags": [
          "Markets"
        ],
        "summary": "Get ETB Securities",
        "description": "The ETB list contains securities that are able to be sold short with a Tradier Brokerage account. The list is quite comprehensive and can result in a long download response time.",
        "operationId": "brokerage-api-markets-get-etb",
        "security": [
          {
            "BearerAuth": []
          }
        ],
        "parameters": [
          {
            "$ref": "#/components/parameters/AcceptHeader"
          }
        ],
        "responses": {
          "200": {
            "description": "Easy to borrow securities",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/EtbResponse"
                },
                "example": {
                  "securities": {
                    "security": [
                      {
                        "symbol": "AAPL"
                      },
                      {
                        "symbol": "SPY"
                      },
                      {
                        "symbol": "QQQ"
                      },
                      {
                        "symbol": "MSFT"
                      },
                      {
                        "symbol": "AMZN"
                      }
                    ]
                  }
                }
              }
            }
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
      "EtbResponse": {
        "type": "object",
        "properties": {
          "securities": {
            "type": "object",
            "properties": {
              "security": {
                "type": "array",
                "items": {
                  "type": "object",
                  "properties": {
                    "symbol": {
                      "type": "string",
                      "description": "The security symbol"
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
}
```