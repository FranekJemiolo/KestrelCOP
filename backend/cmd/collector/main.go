package main

import (
	"context"
	"fmt"
	"log"
	"net/http"
	"os"
	"os/signal"
	"syscall"
	"time"

	"github.com/FranekJemiolo/KestrelCOP/backend/pkg/kafka"
	"github.com/FranekJemiolo/KestrelCOP/backend/pkg/models"
	"github.com/FranekJemiolo/KestrelCOP/backend/pkg/mqtt"
	"github.com/FranekJemiolo/KestrelCOP/backend/pkg/server"
	"github.com/FranekJemiolo/KestrelCOP/backend/pkg/storage"
	"github.com/FranekJemiolo/KestrelCOP/backend/pkg/ws"
)

func getEnv(key string, defaultVal string) string {
	if val := os.Getenv(key); val != "" {
		return val
	}
	return defaultVal
}

func main() {
	log.Println("=====================================================")
	log.Println("🦅 KestrelCOP Tactical Command Collector [v0.1.0]")
	log.Println("Offline-First • Event-Streaming • Cursor-on-Target")
	log.Println("=====================================================")

	mqttURL := getEnv("MQTT_BROKER_URL", "tcp://127.0.0.1:1883")
	mqttTopic := getEnv("MQTT_TOPIC", "tactical/kestrel/+/cot")
	kafkaBrokers := getEnv("KAFKA_BROKERS", "127.0.0.1:9092")
	kafkaTopic := getEnv("KAFKA_TOPIC", "tactical.cot.events")
	postgisDSN := getEnv("POSTGIS_DSN", "")
	httpAddr := getEnv("HTTP_ADDR", ":8080")

	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()

	// 1. Initialize Real-Time WebSocket Hub
	wsHub := ws.NewHub()
	go wsHub.Run()
	log.Println("[INIT] WebSocket broadcast hub initialized.")

	// 2. Initialize PostGIS Storage
	repo, err := storage.NewRepository(postgisDSN)
	if err != nil {
		log.Printf("[INIT] PostGIS init note: %v", err)
	}

	// 3. Initialize Apache Kafka Event Pipeline
	kafkaPipeline := kafka.NewPipeline(kafkaBrokers, kafkaTopic, "kestrel-collector-group")

	// 4. Ingestion Pipeline Handler (invoked for each validated CoT message)
	ingestionHandler := func(rawJSON []byte, parsed *models.CoTMessage) {
		// A. Save to PostGIS / Spatial DB
		saveCtx, saveCancel := context.WithTimeout(ctx, 2*time.Second)
		if err := repo.SaveCoTEvent(saveCtx, parsed); err != nil {
			log.Printf("[PIPELINE] DB error: %v", err)
		}
		saveCancel()

		// B. Publish to Kafka immutable log
		kafkaCtx, kafkaCancel := context.WithTimeout(ctx, 2*time.Second)
		if err := kafkaPipeline.Publish(kafkaCtx, parsed.Event.UID, rawJSON); err != nil {
			log.Printf("[PIPELINE] Kafka publish note: %v", err)
		}
		kafkaCancel()

		// C. Broadcast to active WebSocket COP dashboard clients
		if err := wsHub.BroadcastEvent(parsed); err != nil {
			log.Printf("[PIPELINE] WS broadcast error: %v", err)
		}
	}

	// 5. Connect MQTT Subscriber to Tactical Broker
	sub, err := mqtt.NewSubscriber(mqttURL, "kestrel-collector-srv", mqttTopic, ingestionHandler)
	if err != nil {
		log.Printf("[INIT] MQTT subscriber init note: %v", err)
	}

	// 6. Launch HTTP & WebSocket Server
	srv := server.NewServer(wsHub, repo)
	httpServer := &http.Server{
		Addr:         httpAddr,
		Handler:      srv.Handler(),
		ReadTimeout:  15 * time.Second,
		WriteTimeout: 15 * time.Second,
	}

	go func() {
		log.Printf("[HTTP] Tactical Collector API listening on %s (Endpoints: /healthz, /ws, /api/v1/entities)", httpAddr)
		if err := httpServer.ListenAndServe(); err != nil && err != http.ErrServerClosed {
			log.Fatalf("[HTTP] Server fatal error: %v", err)
		}
	}()

	// 7. Graceful Termination Handling
	stopChan := make(chan os.Signal, 1)
	signal.Notify(stopChan, os.Interrupt, syscall.SIGTERM)

	sig := <-stopChan
	log.Printf("[SHUTDOWN] Received termination signal (%v). Initiating graceful shutdown...", sig)

	// Step A: Signal background routines to stop
	cancel()

	// Step B: Stop incoming HTTP and WebSocket connections
	shutdownCtx, shutdownCancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer shutdownCancel()

	if err := httpServer.Shutdown(shutdownCtx); err != nil {
		log.Printf("[SHUTDOWN] HTTP server shutdown error: %v", err)
	} else {
		log.Println("[SHUTDOWN] HTTP and WebSocket server stopped.")
	}

	// Step C: Disconnect tactical MQTT subscriber
	if sub != nil {
		sub.Disconnect()
		log.Println("[SHUTDOWN] Tactical MQTT subscriber cleanly disconnected.")
	}

	// Step D: Cleanly commit Kafka consumer offsets and flush writer
	if err := kafkaPipeline.Close(); err != nil {
		log.Printf("[SHUTDOWN] Kafka pipeline close warning: %v", err)
	} else {
		log.Println("[SHUTDOWN] Kafka consumer offsets committed and producer flushed.")
	}

	// Step E: Drain and close PostGIS connection pool
	if err := repo.Close(); err != nil {
		log.Printf("[SHUTDOWN] PostGIS connection pool close warning: %v", err)
	} else {
		log.Println("[SHUTDOWN] PostGIS database connection pool closed.")
	}

	fmt.Println("🦅 KestrelCOP Collector halted cleanly.")
}
