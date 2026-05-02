Get Market Lookup

# Get Market Lookup

Search for a symbol using the ticker symbol or partial symbol. Results are in descending order by average volume of the security. This can be used for simple search functions.

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
    "/v1/markets/lookup": {
      "get": {
        "tags": [
          "Markets"
        ],
        "summary": "Get Market Lookup",
        "description": "Search for a symbol using the ticker symbol or partial symbol. Results are in descending order by average volume of the security. This can be used for simple search functions.",
        "operationId": "brokerage-api-markets-get-lookup",
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
            "name": "q",
            "in": "query",
            "required": true,
            "schema": {
              "type": "string"
            },
            "description": "The lookup query (symbol or name)",
            "example": "apple"
          },
          {
            "name": "exchanges",
            "in": "query",
            "required": false,
            "schema": {
              "type": "string",
              "enum": [
                "Q",
                "N",
                "A",
                "B",
                "C",
                "P",
                "I",
                "M",
                "W",
                "Z"
              ]
            },
            "description": "Filter for specific exchanges"
          },
          {
            "name": "types",
            "in": "query",
            "required": false,
            "schema": {
              "type": "string",
              "enum": [
                "stock",
                "etf",
                "index"
              ]
            },
            "description": "Filter for specific security types"
          }
        ],
        "responses": {
          "200": {
            "description": "Lookup results",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/LookupResponse"
                },
                "example": {
                  "securities": {
                    "security": [
                      {
                        "symbol": "AAPL",
                        "exchange": "Q",
                        "type": "stock",
                        "description": "Apple Inc"
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
      "LookupResponse": {
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
                    },
                    "exchange": {
                      "type": "string",
                      "description": "The exchange code"
                    },
                    "type": {
                      "type": "string",
                      "enum": [
                        "stock",
                        "etf",
                        "index",
                        "option",
                        "mutual_fund"
                      ],
                      "description": "The security type"
                    },
                    "description": {
                      "type": "string",
                      "description": "The security description"
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