"""Test batch processing functionality of LTSS."""

import time
import threading
from unittest.mock import Mock, patch
import pytest
import queue

from custom_components.ltss import LTSS_DB


class TestBatchProcessing:
    """Test batch processing functionality."""

    def test_batch_collection_by_size(self):
        """Test that batch collection stops when reaching batch_size."""
        # Create LTSS_DB instance with small batch size for testing
        ltss = LTSS_DB(
            hass=None,
            uri="postgresql://test",
            chunk_time_interval=123,
            batch_size=3,
            batch_timeout_ms=10000,
            poll_interval_ms=50,
            entity_filter=lambda x: True,
        )
        
        # Mock events
        mock_events = [
            Mock(data={"entity_id": f"sensor.test_{i}", "new_state": Mock(state="test", attributes={})}) 
            for i in range(5)
        ]
        
        # Add events to queue
        for event in mock_events:
            ltss.queue.put(event)
        
        # Collect batch
        batch = ltss._collect_batch()
        
        # Should collect 3 events (batch_size)
        assert len(batch) == 3
        assert batch == mock_events[:3]

    def test_batch_collection_by_timeout(self):
        """Test that batch collection stops when reaching timeout."""
        # Create LTSS_DB instance with short timeout
        ltss = LTSS_DB(
            hass=None,
            uri="postgresql://test",
            chunk_time_interval=123,
            batch_size=100,
            batch_timeout_ms=200,
            poll_interval_ms=50,
            entity_filter=lambda x: True,
        )
        
        # Add few events
        mock_events = [
            Mock(data={"entity_id": f"sensor.test_{i}", "new_state": Mock(state="test", attributes={})}) 
            for i in range(2)
        ]
        
        for event in mock_events:
            ltss.queue.put(event)
        
        # Collect batch
        start_time = time.time()
        batch = ltss._collect_batch()
        end_time = time.time()
        
        # Should collect all events and wait for timeout
        assert len(batch) == 2
        assert (end_time - start_time) >= 0.2

    def test_is_batch_timeout(self):
        """Test batch timeout detection."""
        ltss = LTSS_DB(
            hass=None,
            uri="postgresql://test", 
            chunk_time_interval=123,
            batch_size=100,
            batch_timeout_ms=500,
            poll_interval_ms=50,
            entity_filter=lambda x: True,
        )
        
        # Test not timed out
        current_time = time.time() * 1000
        assert not ltss._is_batch_timeout(current_time)
        
        # Test timed out
        old_time = current_time - 600
        assert ltss._is_batch_timeout(old_time)
        
        # Test None
        assert not ltss._is_batch_timeout(None)

    @patch('custom_components.ltss.LTSS')
    def test_process_batch_success(self, mock_ltss_class):
        """Test successful batch processing."""
        # Setup mocks
        mock_session = Mock()
        mock_session.begin.return_value.__enter__ = Mock(return_value=mock_session)
        mock_session.begin.return_value.__exit__ = Mock(return_value=None)
        
        ltss = LTSS_DB(
            hass=None,
            uri="postgresql://test",
            chunk_time_interval=123,
            batch_size=100,
            batch_timeout_ms=5000,
            poll_interval_ms=50,
            entity_filter=lambda x: True,
        )
        
        # Mock get_session
        ltss.get_session = Mock(return_value=mock_session)
        ltss.get_session.return_value.__enter__ = Mock(return_value=mock_session)
        ltss.get_session.return_value.__exit__ = Mock(return_value=None)
        
        # Mock events and LTSS.from_event
        mock_events = [Mock() for _ in range(3)]
        mock_rows = [Mock() for _ in range(3)]
        mock_ltss_class.from_event.side_effect = mock_rows
        
        # Put events in queue for task_done to work properly
        for event in mock_events:
            ltss.queue.put(event)
        
        # Process batch
        ltss._process_batch(mock_events)
        
        # Verify all events were processed
        assert mock_ltss_class.from_event.call_count == 3
        assert mock_session.add.call_count == 3

    def test_empty_batch_processing(self):
        """Test that empty batch is handled gracefully."""
        ltss = LTSS_DB(
            hass=None,
            uri="postgresql://test",
            chunk_time_interval=123,
            batch_size=100,
            batch_timeout_ms=5000,
            poll_interval_ms=50,
            entity_filter=lambda x: True,
        )
        
        # Empty batch should not cause errors
        ltss._process_batch([])
        
        # Should also handle None
        ltss._process_batch(None)

    def test_shutdown_signal_handling(self):
        """Test that shutdown signal (None) is properly handled."""
        ltss = LTSS_DB(
            hass=None,
            uri="postgresql://test",
            chunk_time_interval=123,
            batch_size=100,
            batch_timeout_ms=5000,
            poll_interval_ms=50,
            entity_filter=lambda x: True,
        )
        
        # Add some normal events
        mock_events = [Mock() for _ in range(2)]
        for event in mock_events:
            ltss.queue.put(event)
        
        # Add shutdown signal
        ltss.queue.put(None)
        
        # Collect batch
        batch = ltss._collect_batch()
        
        # Batch should contain normal events and None marker
        assert len(batch) == 3
        assert batch[:2] == mock_events
        assert batch[2] is None
        
        # Verify queue is empty (all events including None were processed)
        assert ltss.queue.empty()

    def test_shutdown_signal_only(self):
        """Test shutdown signal when no other events are present."""
        ltss = LTSS_DB(
            hass=None,
            uri="postgresql://test",
            chunk_time_interval=123,
            batch_size=100,
            batch_timeout_ms=5000,
            poll_interval_ms=50,
            entity_filter=lambda x: True,
        )
        
        # Add only shutdown signal
        ltss.queue.put(None)
        
        # Collect batch
        batch = ltss._collect_batch()
        
        # Batch should only contain None marker
        assert len(batch) == 1
        assert batch[0] is None
        
        # Verify queue is empty
        assert ltss.queue.empty()

    def test_mixed_events_with_shutdown(self):
        """Test handling of mixed normal events and shutdown signal."""
        ltss = LTSS_DB(
            hass=None,
            uri="postgresql://test",
            chunk_time_interval=123,
            batch_size=10,
            batch_timeout_ms=5000,
            poll_interval_ms=50,
            entity_filter=lambda x: True,
        )
        
        # Add normal events, then shutdown signal
        mock_events = [Mock() for _ in range(3)]
        for event in mock_events:
            ltss.queue.put(event)
        ltss.queue.put(None)
        
        # Collect batch
        batch = ltss._collect_batch()
        
        # Batch should contain all normal events + None marker
        assert len(batch) == 4
        assert batch[:3] == mock_events
        assert batch[3] is None
        
        # Verify queue is empty
        assert ltss.queue.empty()
        
        # Test shutdown processing logic
        shutdown_received = None in batch
        assert shutdown_received
        
        actual_events = [event for event in batch if event is not None]
        assert len(actual_events) == 3
        assert actual_events == mock_events

    @patch('custom_components.ltss.LTSS')
    def test_exact_task_done_count_matching(self, mock_ltss_class):
        """Test that task_done is called exactly the same number of times as put."""
        # Setup mocks
        mock_session = Mock()
        mock_session.begin.return_value.__enter__ = Mock(return_value=mock_session)
        mock_session.begin.return_value.__exit__ = Mock(return_value=None)
        
        ltss = LTSS_DB(
            hass=None,
            uri="postgresql://test",
            chunk_time_interval=123,
            batch_size=3,
            batch_timeout_ms=5000,
            poll_interval_ms=50,
            entity_filter=lambda x: True,
        )
        
        # Mock get_session
        ltss.get_session = Mock(return_value=mock_session)
        ltss.get_session.return_value.__enter__ = Mock(return_value=mock_session)
        ltss.get_session.return_value.__exit__ = Mock(return_value=None)
        
        # Mock LTSS.from_event
        mock_ltss_class.from_event.return_value = Mock()
        
        # Mock queue's task_done method to count calls
        original_task_done = ltss.queue.task_done
        task_done_count = 0
        
        def count_task_done():
            nonlocal task_done_count
            task_done_count += 1
            return original_task_done()
        
        ltss.queue.task_done = count_task_done
        
        # Test scenario 1: Normal batch processing
        put_count = 0
        mock_events = [Mock() for _ in range(5)]
        for event in mock_events:
            ltss.queue.put(event)
            put_count += 1
        
        # Collect and process first batch (3 events)
        batch1 = ltss._collect_batch()
        assert len(batch1) == 3
        ltss._process_batch(batch1)
        
        # Collect and process second batch (2 events)
        batch2 = ltss._collect_batch()
        assert len(batch2) == 2
        ltss._process_batch(batch2)
        
        # Verify task_done call count matches put count
        assert task_done_count == put_count == 5
        
        # Reset counters
        task_done_count = 0
        put_count = 0
        
        # Test scenario 2: With shutdown signal
        mock_events2 = [Mock() for _ in range(2)]
        for event in mock_events2:
            ltss.queue.put(event)
            put_count += 1
        
        ltss.queue.put(None)
        put_count += 1
        
        # Collect batch (should contain 2 events + None)
        batch3 = ltss._collect_batch()
        assert len(batch3) == 3
        assert batch3[2] is None
        
        # Process actual events (excluding None)
        actual_events = [event for event in batch3 if event is not None]
        ltss._process_batch(actual_events)
        
        # Verify task_done call count matches put count (including None's task_done)
        assert task_done_count == put_count == 3
        
        # Verify queue is completely empty
        assert ltss.queue.empty()
