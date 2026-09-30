package kafka

import (
	"context"
	"testing"
)

func TestPipeline_BypassAndClose(t *testing.T) {
	p := NewPipeline("", "tactical.cot.events", "test-group")
	if p.connected {
		t.Fatalf("expected pipeline to be disconnected in bypass mode")
	}

	ctx := context.Background()
	err := p.Publish(ctx, "test-uid", []byte(`{"event":{}}`))
	if err != nil {
		t.Fatalf("expected nil error on publish in bypass mode, got %v", err)
	}

	if err := p.Close(); err != nil {
		t.Fatalf("expected clean close, got %v", err)
	}
}
