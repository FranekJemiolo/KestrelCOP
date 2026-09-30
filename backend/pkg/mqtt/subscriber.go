package mqtt

import (
	"fmt"
	"log"
	"time"

	pahomqtt "github.com/eclipse/paho.mqtt.golang"
	"github.com/FranekJemiolo/KestrelCOP/backend/pkg/models"
)

// IngestionHandler callback signature for validated CoT messages.
type IngestionHandler func(rawJSON []byte, parsed *models.CoTMessage)

// Subscriber manages MQTT subscription to tactical edge nodes.
type Subscriber struct {
	client  pahomqtt.Client
	topic   string
	handler IngestionHandler
}

// NewSubscriber creates an MQTT client connected to the MANET broker.
func NewSubscriber(brokerURL string, clientID string, topic string, handler IngestionHandler) (*Subscriber, error) {
	opts := pahomqtt.NewClientOptions()
	opts.AddBroker(brokerURL)
	opts.SetClientID(clientID)
	opts.SetAutoReconnect(true)
	opts.SetMaxReconnectInterval(5 * time.Second)
	opts.SetKeepAlive(30 * time.Second)

	sub := &Subscriber{
		topic:   topic,
		handler: handler,
	}

	opts.SetOnConnectHandler(func(c pahomqtt.Client) {
		log.Printf("[MQTT-SUB] Connected to broker %s. Subscribing to topic: %s", brokerURL, topic)
		token := c.Subscribe(topic, 1, sub.onMessageReceived)
		if token.Wait() && token.Error() != nil {
			log.Printf("[MQTT-SUB] Subscription error: %v", token.Error())
		}
	})

	opts.SetConnectionLostHandler(func(c pahomqtt.Client, err error) {
		log.Printf("[MQTT-SUB] Tactical radio link lost: %v. Reconnection active...", err)
	})

	client := pahomqtt.NewClient(opts)
	sub.client = client

	log.Printf("[MQTT-SUB] Connecting to broker at %s...", brokerURL)
	token := client.Connect()
	if token.WaitTimeout(4 * time.Second) {
		if token.Error() != nil {
			log.Printf("[MQTT-SUB] Initial connection failed: %v. Background retry enabled.", token.Error())
		}
	} else {
		log.Println("[MQTT-SUB] Connection attempt timed out; will retry in background.")
	}

	return sub, nil
}

func (s *Subscriber) onMessageReceived(_ pahomqtt.Client, msg pahomqtt.Message) {
	payload := msg.Payload()

	// Parse and validate Cursor-on-Target schema
	cotMsg, err := models.ParseCoTJSON(payload)
	if err != nil {
		log.Printf("[MQTT-SUB] REJECTED malformed telemetry on %s: %v", msg.Topic(), err)
		return
	}

	// Forward validated event to ingestion pipeline
	if s.handler != nil {
		s.handler(payload, cotMsg)
	}
}

// Disconnect terminates the MQTT client connection.
func (s *Subscriber) Disconnect() {
	if s.client != nil && s.client.IsConnected() {
		s.client.Disconnect(250)
		fmt.Println("[MQTT-SUB] Disconnected from tactical broker.")
	}
}
