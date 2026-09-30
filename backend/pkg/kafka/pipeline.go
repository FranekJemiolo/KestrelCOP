package kafka

import (
	"context"
	"errors"
	"fmt"
	"log"
	"strings"
	"sync"
	"time"

	"github.com/segmentio/kafka-go"
)

// Pipeline manages publishing and consuming of Cursor-on-Target events via Kafka.
type Pipeline struct {
	writer    *kafka.Writer
	reader    *kafka.Reader
	brokers   []string
	topic     string
	connected bool
	mu        sync.RWMutex
}

// NewPipeline initializes a Kafka writer and reader.
func NewPipeline(brokerList string, topic string, consumerGroup string) *Pipeline {
	brokers := strings.Split(brokerList, ",")
	for i := range brokers {
		brokers[i] = strings.TrimSpace(brokers[i])
	}

	p := &Pipeline{
		brokers: brokers,
		topic:   topic,
	}

	if len(brokers) == 0 || brokers[0] == "" {
		log.Println("[KAFKA] No Kafka brokers specified. Running in bypass mode.")
		return p
	}

	p.writer = &kafka.Writer{
		Addr:         kafka.TCP(brokers...),
		Topic:        topic,
		Balancer:     &kafka.LeastBytes{},
		WriteTimeout: 3 * time.Second,
		Async:        false,
	}

	p.reader = kafka.NewReader(kafka.ReaderConfig{
		Brokers:        brokers,
		GroupID:        consumerGroup,
		Topic:          topic,
		MinBytes:       1,
		MaxBytes:       10e6, // 10MB
		CommitInterval: time.Second,
		StartOffset:    kafka.LastOffset,
	})

	p.connected = true
	log.Printf("[KAFKA] Kafka pipeline configured on brokers: %s (Topic: %s)", brokerList, topic)
	return p
}

// Publish sends a CoT message payload to the Kafka event log.
func (p *Pipeline) Publish(ctx context.Context, uid string, payload []byte) error {
	p.mu.RLock()
	defer p.mu.RUnlock()

	if !p.connected || p.writer == nil {
		return nil
	}

	msg := kafka.Message{
		Key:   []byte(uid),
		Value: payload,
		Time:  time.Now().UTC(),
	}

	err := p.writer.WriteMessages(ctx, msg)
	if err != nil {
		return err
	}
	return nil
}

// StartConsumer begins listening for committed Kafka events.
func (p *Pipeline) StartConsumer(ctx context.Context, handler func(payload []byte) error) {
	p.mu.RLock()
	connected := p.connected
	reader := p.reader
	p.mu.RUnlock()

	if !connected || reader == nil {
		return
	}

	log.Println("[KAFKA] Starting consumer loop...")
	for {
		select {
		case <-ctx.Done():
			log.Println("[KAFKA] Consumer loop stopping on context cancellation.")
			return
		default:
			msg, err := reader.FetchMessage(ctx)
			if err != nil {
				if errors.Is(err, context.Canceled) {
					return
				}
				time.Sleep(500 * time.Millisecond)
				continue
			}

			if err := handler(msg.Value); err != nil {
				log.Printf("[KAFKA] Error handling consumed CoT event: %v", err)
			}

			if err := reader.CommitMessages(ctx, msg); err != nil {
				log.Printf("[KAFKA] Failed committing message offset: %v", err)
			}
		}
	}
}

// Close gracefully terminates Kafka network connections, committing consumer offsets and flushing writer batches.
func (p *Pipeline) Close() error {
	p.mu.Lock()
	defer p.mu.Unlock()

	if !p.connected {
		return nil
	}

	var errs []string
	if p.reader != nil {
		log.Println("[KAFKA] Committing pending offsets and closing consumer...")
		if err := p.reader.Close(); err != nil {
			errs = append(errs, fmt.Sprintf("reader close: %v", err))
		}
	}
	if p.writer != nil {
		log.Println("[KAFKA] Flushing message buffer and closing producer...")
		if err := p.writer.Close(); err != nil {
			errs = append(errs, fmt.Sprintf("writer close: %v", err))
		}
	}
	p.connected = false

	if len(errs) > 0 {
		return errors.New(strings.Join(errs, "; "))
	}
	log.Println("[KAFKA] Pipeline shutdown complete: offsets committed and sockets released.")
	return nil
}
