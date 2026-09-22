-- Read-only view of the saved gateway OTLP. Run against each sealed monitor.db.
-- Keep Run identity and raw JSON so new analyses can inspect unprojected fields.
-- NULL means unreported; this query does not certify complete Run usage.
WITH spans AS (
    SELECT records.id AS raw_record_id,
           resource.value AS resource_json,
           span.value AS span_json
    FROM raw_records AS records,
         json_each(records.payload_json, '$.resourceSpans') AS resource,
         json_each(resource.value, '$.scopeSpans') AS scope,
         json_each(scope.value, '$.spans') AS span
)
SELECT raw_record_id,
    (SELECT json_extract(value, '$.value.stringValue')
     FROM json_each(resource_json, '$.resource.attributes')
     WHERE json_extract(value, '$.key') = 'run.id') AS run_id,
    (SELECT json_extract(value, '$.value.stringValue')
     FROM json_each(resource_json, '$.resource.attributes')
     WHERE json_extract(value, '$.key') = 'sample2.run_instance_id') AS run_instance_id,
    json_extract(span_json, '$.traceId') AS trace_id,
    json_extract(span_json, '$.spanId') AS span_id,
    (SELECT json_extract(value, '$.value.stringValue')
     FROM json_each(span_json, '$.attributes')
     WHERE json_extract(value, '$.key') = 'sample2.request.id') AS request_id,
    (SELECT json_extract(value, '$.value.stringValue')
     FROM json_each(span_json, '$.attributes')
     WHERE json_extract(value, '$.key') = 'gen_ai.conversation.id') AS conversation_id,
    (SELECT json_extract(value, '$.value.stringValue')
     FROM json_each(span_json, '$.attributes')
     WHERE json_extract(value, '$.key') = 'gen_ai.request.model') AS model_id,
    (SELECT json_extract(value, '$.value.stringValue')
     FROM json_each(span_json, '$.attributes')
     WHERE json_extract(value, '$.key') = 'sample2.request.status') AS request_status,
    json_extract(span_json, '$.startTimeUnixNano') AS start_time_unix_nano,
    json_extract(span_json, '$.endTimeUnixNano') AS end_time_unix_nano,
    (SELECT CAST(json_extract(value, '$.value.intValue') AS INTEGER)
     FROM json_each(span_json, '$.attributes')
     WHERE json_extract(value, '$.key') = 'gen_ai.usage.input_tokens') AS input_tokens,
    (SELECT CAST(json_extract(value, '$.value.intValue') AS INTEGER)
     FROM json_each(span_json, '$.attributes')
     WHERE json_extract(value, '$.key') = 'gen_ai.usage.output_tokens') AS output_tokens,
    (SELECT CAST(json_extract(value, '$.value.intValue') AS INTEGER)
     FROM json_each(span_json, '$.attributes')
     WHERE json_extract(value, '$.key') = 'sample2.cache_read_tokens') AS cache_read_tokens,
    (SELECT CAST(json_extract(value, '$.value.intValue') AS INTEGER)
     FROM json_each(span_json, '$.attributes')
     WHERE json_extract(value, '$.key') = 'sample2.cache_write_tokens') AS cache_write_tokens,
    (SELECT CAST(json_extract(value, '$.value.intValue') AS INTEGER)
     FROM json_each(span_json, '$.attributes')
     WHERE json_extract(value, '$.key') = 'sample2.reasoning_tokens') AS reasoning_tokens,
    json_extract(resource_json, '$.resource.attributes') AS resource_attributes_json,
    span_json
FROM spans
ORDER BY raw_record_id, start_time_unix_nano, span_id;
