package kafka

import (
	"context"
	"errors"
	"log"
	"strings"
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
	if !p.connected || p.reader == nil {
		return
	}

	log.Println("[KAFKA] Starting consumer loop...")
	for {
		select {
		case <-ctx.Done():
			log.Println("[KAFKA] Consumer loop stopping on context cancellation.")
			return
		default:
			msg, err := p.reader.FetchMessage(ctx)
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

			if err := p.reader.CommitMessages(ctx, msg); err != nil {
				log.Printf("[KAFKA] Failed committing message offset: %v", err)
			}
		}
	}
}

// Close gracefully terminates Kafka network connections.
func (p *Pipeline) Close() error {
	var errs []string
	if p.writer != nil {
		if err := p.writer.Close(); err != nil {
			errs = append(errs, err.Error())
		}
	}
	if p.reader != nil {
		if err := p.reader.Close(); err != nil {
			errs = append(errs, err.Error())
		}
	}
	if len(errs) > 0 {
		return errors.New(strings.Join(errs, "; "))
	}
	return nil
}
