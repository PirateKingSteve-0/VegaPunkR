Get Options Strikes

# Get Options Strikes

Get available strike prices for a specific underlying symbol and expiration date

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
    "/v1/markets/options/strikes": {
      "get": {
        "tags": [
          "Markets"
        ],
        "summary": "Get Options Strikes",
        "description": "Get available strike prices for a specific underlying symbol and expiration date",
        "operationId": "brokerage-api-markets-get-options-strikes",
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
          }
        ],
        "responses": {
          "200": {
            "description": "Available strike prices",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/StrikesResponse"
                },
                "example": {
                  "strikes": {
                    "strike": [
                      115,
                      120,
                      125,
                      130,
                      135
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
      "StrikesResponse": {
        "type": "object",
        "properties": {
          "strikes": {
            "type": "object",
            "properties": {
              "strike": {
                "type": "array",
                "items": {
                  "type": "number",
                  "format": "float"
                },
                "description": "List of available strike prices"
              }
            }
          }
        }
      }
    }
  }
}
```