package main

import (
	"encoding/json"
	"log"
	"net/http"
	"os"
)

var version = "dev" // overridden at build time via -ldflags "-X main.version=x.y.z"

type Hotel struct {
	ID       string  `json:"id"`
	Name     string  `json:"name"`
	City     string  `json:"city"`
	Stars    int     `json:"stars"`
	PriceUSD float64 `json:"price_per_night_usd"`
	Available bool   `json:"available"`
}

var hotels = []Hotel{
	{"H001", "Grand Pacific", "San Francisco", 5, 420.00, true},
	{"H002", "The Urban Stay", "New York", 4, 310.00, true},
	{"H003", "Sunset Resort", "Miami", 4, 275.00, false},
	{"H004", "Lakeview Inn", "Chicago", 3, 145.00, true},
}

func main() {
	port := os.Getenv("PORT")
	if port == "" {
		port = "9081"
	}

	mux := http.NewServeMux()
	mux.HandleFunc("/", handleRoot)
	mux.HandleFunc("/hotels", handleHotels)
	mux.HandleFunc("/healthz", handleHealth)
	mux.HandleFunc("/status", handleStatus)

	log.Printf("travel-hotels %s listening on :%s", version, port)
	if err := http.ListenAndServe(":"+port, mux); err != nil {
		log.Fatal(err)
	}
}

func handleRoot(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(map[string]interface{}{
		"service":    "travel-hotels",
		"version":    version,
		"properties": len(hotels),
	})
}

func handleHotels(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(hotels)
}

func handleHealth(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(http.StatusOK)
	json.NewEncoder(w).Encode(map[string]string{"status": "ok"})
}

func handleStatus(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(map[string]interface{}{
		"service":    "travel-hotels",
		"version":    version,
		"status":     "running",
		"properties": len(hotels),
	})
}
