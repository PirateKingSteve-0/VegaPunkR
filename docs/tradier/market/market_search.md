Get Market Search

# Get Market Search

Search for securities by partial match on symbol or company name. Results are in descending order by average volume of the security. This can be used for simple search functions

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
    "/v1/markets/search": {
      "get": {
        "tags": [
          "Markets"
        ],
        "summary": "Get Market Search",
        "description": "Search for securities by partial match on symbol or company name. Results are in descending order by average volume of the security. This can be used for simple search functions",
        "operationId": "brokerage-api-markets-get-search",
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
            "description": "The search query (symbol or name)",
            "example": "app"
          },
          {
            "name": "indexes",
            "in": "query",
            "required": false,
            "schema": {
              "type": "boolean",
              "default": false
            },
            "description": "Include indices in the results"
          }
        ],
        "responses": {
          "200": {
            "description": "Search results",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/SearchResponse"
                },
                "example": {
                  "securities": {
                    "security": [
                      {
                        "symbol": "AAPL",
                        "exchange": "Q",
                        "type": "stock",
                        "description": "Apple Inc"
                      },
                      {
                        "symbol": "APPL",
                        "exchange": "A",
                        "type": "stock",
                        "description": "Appell Petroleum Corp"
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
      "SearchResponse": {
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