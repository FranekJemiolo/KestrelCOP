# -----------------------------------------------------------------------------
# KestrelCOP Go Collector Backend Dockerfile
# Multi-stage security-hardened distroless build (Zero-shell, minimal attack surface)
# -----------------------------------------------------------------------------

FROM golang:1.24-alpine AS builder

RUN apk add --no-cache git ca-certificates tzdata

WORKDIR /app

# Cache dependencies
COPY go.mod go.sum ./
RUN go mod download

# Copy source
COPY . .

# Compile static, stripped binary without CGO for portability
RUN CGO_ENABLED=0 go build -trimpath -ldflags="-w -s" -o /collector ./cmd/collector

# -----------------------------------------------------------------------------
# Production Runtime Stage: Distroless Static Non-Root
# -----------------------------------------------------------------------------
FROM gcr.io/distroless/static-debian12:nonroot

WORKDIR /app

# Copy binary from builder
COPY --from=builder /collector /app/collector

# Switch to unprivileged distroless user
USER nonroot:nonroot

EXPOSE 8080 9090

ENTRYPOINT ["/app/collector"]
