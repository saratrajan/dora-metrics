FROM golang:1.22-alpine AS builder
WORKDIR /src
COPY app/main.go .
RUN go mod init travel-flights && go build -o flights .

FROM alpine:3.19
WORKDIR /app
COPY --from=builder /src/flights .
EXPOSE 9080
ENTRYPOINT ["./flights"]
