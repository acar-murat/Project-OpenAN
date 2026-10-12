## Subscription Description
Based on the following <Notification Topic>, <Subscribe Condition>, <Notification Data Format>, and <Expected Output> information, complete the network-side intelligent fault Incident subscription and reporting task.

## Notification Topic
{{notification_topic}} (required)
Requirement: Provide the topic name of the intelligent fault Incident. The specific name can be Incident, Fault, intelligent fault, fault, etc.

## Subscribe Condition
{{subscribe_condition}} (optional)
Requirement: The subscription condition includes fault priority and fault name.
Fault priority: supports passing a list. The allowed values of this parameter include critical, high, medium, and low.
Fault name: supports passing a list. The allowed values of this parameter are the list of network-side fault names, for example: pigtail fault, fiber break, board fault, optical module fault, etc.

## Notification Data Format
{{notification_data_format}} (optional)
Requirement: 1. Reported data type: Incident, fault; 2. Reported data format: which A2A Part carries it (DataPart, TextPart).
For example: report Incident data via DataPart.

## Expected Output
1. Subscription result, success or failure
2. Reason for subscription failure (optional)
