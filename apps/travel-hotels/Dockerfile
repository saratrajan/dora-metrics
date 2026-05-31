FROM golang:1.22-alpine AS builder
WORKDIR /src
COPY app/main.go .
RUN go mod init travel-hotels && go build -o hotels .

FROM alpine:3.19
WORKDIR /app
COPY --from=builder /src/hotels .
EXPOSE 9081
ENTRYPOINT ["./hotels"]
