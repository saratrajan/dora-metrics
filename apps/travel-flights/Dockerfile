FROM golang:1.22-alpine AS builder
ARG VERSION=dev
WORKDIR /src
COPY app/main.go .
RUN go mod init travel-flights && go build -ldflags "-X main.version=${VERSION}" -o flights .

FROM alpine:3.19
WORKDIR /app
COPY --from=builder /src/flights .
EXPOSE 9080
ENTRYPOINT ["./flights"]
