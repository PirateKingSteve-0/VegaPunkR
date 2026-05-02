Create Market Session

# Create Market Session

Create a session for streaming market data

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
    "/v1/markets/events/session": {
      "post": {
        "tags": [
          "Streaming"
        ],
        "summary": "Create Market Session",
        "description": "Create a session for streaming market data",
        "operationId": "brokerage-api-streaming-create-market-session",
        "security": [
          {
            "BearerAuth": []
          }
        ],
        "parameters": [
          {
            "$ref": "#/components/parameters/ContentTypeHeader"
          },
          {
            "$ref": "#/components/parameters/AcceptHeader"
          }
        ],
        "requestBody": {
          "required": false,
          "content": {}
        },
        "responses": {
          "200": {
            "description": "Successfully created market streaming session",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/StreamingSessionResponse"
                },
                "example": {
                  "stream": {
                    "url": "wss://ws.tradier.com/v1/markets/events",
                    "sessionid": "123e4567-e89b-12d3-a456-426614174000"
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
      }
    },
    "responses": {
      "Unauthorized": {
        "description": "Authentication required or invalid credentials"
      },
      "Forbidden": {
        "description": "Access denied to the requested resource"
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
      "StreamingSessionResponse": {
        "type": "object",
        "properties": {
          "stream": {
            "type": "object",
            "properties": {
              "url": {
                "type": "string",
                "description": "The WebSocket URL for the streaming session"
              },
              "sessionid": {
                "type": "string",
                "description": "The session ID for the streaming session"
              },
              "expires": {
                "type": "string",
                "format": "date-time",
                "description": "The expiration time of the session"
              }
            }
          }
        }
      }
    }
  }
}
```