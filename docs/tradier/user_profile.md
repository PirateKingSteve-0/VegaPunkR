Get User Profile

# Get User Profile

Get the profile information for the current user

# Credentials

BEARER BEARER<ACCESS_TOKEN>

# URL

## Live server
https://api.tradier.com/v1/user/profile

## Sandbox
https://sandbox.tradier.com/v1/user/profile

# Request (Example)

```python
import requests

url = "https://sandbox.tradier.com/v1/user/profile"

headers = {"Accept": "application/json"}

response = requests.get(url, headers=headers)

print(response.text)
```

# Response Example

```json
{
  "profile": {
    "id": "id-123456",
    "name": "John Doe",
    "account": [
      {
        "account_number": "VA000001",
        "classification": "individual",
        "date_created": "2015-01-01T15:25:47.000Z",
        "day_trader": true,
        "option_level": 4,
        "status": "active",
        "type": "margin",
        "last_update_date": "2015-01-01T15:25:47.000Z"
      }
    ]
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
    "/v1/user/profile": {
      "get": {
        "tags": [
          "User"
        ],
        "summary": "Get User Profile",
        "description": "Get the profile information for the current user",
        "operationId": "brokerage-api-user-get-profile",
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
            "description": "User profile information",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/ProfileResponse"
                },
                "example": {
                  "profile": {
                    "id": "id-123456",
                    "name": "John Doe",
                    "account": [
                      {
                        "account_number": "VA000001",
                        "classification": "individual",
                        "date_created": "2015-01-01T15:25:47.000Z",
                        "day_trader": true,
                        "option_level": 4,
                        "status": "active",
                        "type": "margin",
                        "last_update_date": "2015-01-01T15:25:47.000Z"
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
      "ProfileResponse": {
        "type": "object",
        "properties": {
          "profile": {
            "type": "object",
            "properties": {
              "id": {
                "type": "string",
                "description": "The unique ID assigned to the user"
              },
              "name": {
                "type": "string",
                "description": "The user's full name"
              },
              "account": {
                "type": "array",
                "items": {
                  "$ref": "#/components/schemas/Account"
                }
              }
            }
          }
        }
      },
      "Account": {
        "type": "object",
        "properties": {
          "account_number": {
            "type": "string",
            "description": "The account number"
          },
          "classification": {
            "type": "string",
            "description": "The account classification (individual, corporate, etc.)",
            "enum": [
              "individual",
              "corporate",
              "joint",
              "ira",
              "roth_ira",
              "entity"
            ]
          },
          "date_created": {
            "type": "string",
            "format": "date-time",
            "description": "The date the account was created"
          },
          "day_trader": {
            "type": "boolean",
            "description": "Whether the account is marked as a day trader"
          },
          "option_level": {
            "type": "integer",
            "description": "The option level approval for the account (1-4)"
          },
          "status": {
            "type": "string",
            "description": "The account status",
            "enum": [
              "active",
              "closed"
            ]
          },
          "type": {
            "type": "string",
            "description": "The account type",
            "enum": [
              "cash",
              "margin"
            ]
          },
          "last_update_date": {
            "type": "string",
            "format": "date-time",
            "description": "The date the account was last updated"
          }
        }
      }
    }
  }
}
```