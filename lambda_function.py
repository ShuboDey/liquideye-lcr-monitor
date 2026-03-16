import json
import boto3
from datetime import datetime, timezone
from decimal import Decimal

s3_client = boto3.client("s3")
sns_client = boto3.client("sns")
cloudwatch_client = boto3.client("cloudwatch")
dynamodb = boto3.resource("dynamodb")
table = dynamodb.Table("liquideye-lcr-results")

# ========================================================
# PASTE YOUR SNS TOPIC ARN BELOW
# ========================================================
SNS_TOPIC_ARN = "arn:aws:sns:REGION:ACCOUNT_ID:liquideye-lcr-alerts"

# Basel III HQLA haircuts
HAIRCUTS = {
    "level_1": 0.00,
    "level_2a": 0.15,
    "level_2b": 0.50
}

LCR_THRESHOLD = 100.0
INFLOW_CAP_RATE = 0.75


def calculate_effective_hqla(hqla):
    """Apply Basel III haircuts to each HQLA level."""
    effective = {}
    for level, amount in hqla.items():
        haircut = HAIRCUTS.get(level, 0.0)
        effective[level] = amount * (1 - haircut)
    return effective


def calculate_lcr(data):
    """
    LCR = Effective HQLA / Net Cash Outflows over 30 days
    Net Outflows = Total Outflows - min(Total Inflows, 75% of Total Outflows)
    """
    effective_hqla = calculate_effective_hqla(data["hqla"])
    total_hqla = sum(effective_hqla.values())

    total_outflows = sum(data["cash_outflows_30d"].values())
    total_inflows = sum(data["cash_inflows_30d"].values())

    capped_inflows = min(total_inflows, INFLOW_CAP_RATE * total_outflows)
    net_outflows = total_outflows - capped_inflows

    if net_outflows <= 0:
        return 999.99, total_hqla, net_outflows

    lcr = (total_hqla / net_outflows) * 100
    return round(lcr, 2), round(total_hqla, 2), round(net_outflows, 2)


def store_result(result):
    """Write the LCR result to DynamoDB."""
    item = {
        "bank_id": result["bank_id"],
        "report_date": result["report_date"],
        "currency": result["currency"],
        "effective_hqla": Decimal(str(result["effective_hqla"])),
        "net_outflows_30d": Decimal(str(result["net_outflows_30d"])),
        "lcr_percent": Decimal(str(result["lcr_percent"])),
        "threshold": Decimal(str(result["threshold"])),
        "status": result["status"],
        "source_file": result["source_file"],
        "processed_at": datetime.now(timezone.utc).isoformat()
    }

    table.put_item(Item=item)
    print(f"Stored result in DynamoDB for {result['bank_id']} on {result['report_date']}")


def send_breach_alert(result):
    """Publish an SNS alert when LCR breaches the Basel III threshold."""
    subject = f"LCR BREACH ALERT - {result['bank_id']} - {result['report_date']}"

    message = f"""
=====================================
  LIQUIDITY COVERAGE RATIO BREACH
=====================================

Bank:            {result['bank_id']}
Report Date:     {result['report_date']}
Currency:        {result['currency']}

LCR:             {result['lcr_percent']}%
Threshold:       {result['threshold']}%
Shortfall:       {round(result['threshold'] - result['lcr_percent'], 2)} percentage points

Effective HQLA:  {result['currency']} {result['effective_hqla']:,.2f}
Net Outflows:    {result['currency']} {result['net_outflows_30d']:,.2f}

Status:          {result['status']}
Source File:     {result['source_file']}
Processed At:    {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}

ACTION REQUIRED: Immediate review by Treasury/Risk team.
=====================================
"""

    sns_client.publish(
        TopicArn=SNS_TOPIC_ARN,
        Subject=subject,
        Message=message
    )
    print(f"Breach alert sent for {result['bank_id']} on {result['report_date']}")


def publish_metrics(result):
    """Publish custom CloudWatch metrics for the LCR dashboard."""
    dimensions = [
        {"Name": "BankId", "Value": result["bank_id"]},
        {"Name": "Currency", "Value": result["currency"]}
    ]

    metrics = [
        {
            "MetricName": "LCR_Percent",
            "Dimensions": dimensions,
            "Value": result["lcr_percent"],
            "Unit": "Percent"
        },
        {
            "MetricName": "Effective_HQLA",
            "Dimensions": dimensions,
            "Value": result["effective_hqla"],
            "Unit": "None"
        },
        {
            "MetricName": "Net_Outflows_30d",
            "Dimensions": dimensions,
            "Value": result["net_outflows_30d"],
            "Unit": "None"
        },
        {
            "MetricName": "LCR_Breach",
            "Dimensions": dimensions,
            "Value": 1.0 if result["status"] == "BREACH" else 0.0,
            "Unit": "Count"
        }
    ]

    cloudwatch_client.put_metric_data(
        Namespace="LiquidEye",
        MetricData=metrics
    )
    print(f"Published CloudWatch metrics for {result['bank_id']} on {result['report_date']}")


def lambda_handler(event, context):
    """Triggered by S3 PutObject event."""

    record = event["Records"][0]
    bucket = record["s3"]["bucket"]["name"]
    key = record["s3"]["object"]["key"]

    print(f"Processing file: s3://{bucket}/{key}")

    # Read the file from S3
    response = s3_client.get_object(Bucket=bucket, Key=key)
    data = json.loads(response["Body"].read().decode("utf-8"))

    # Calculate LCR
    lcr, total_hqla, net_outflows = calculate_lcr(data)

    # Determine status
    if lcr < LCR_THRESHOLD:
        status = "BREACH"
    elif lcr < 110:
        status = "WARNING"
    else:
        status = "HEALTHY"

    result = {
        "bank_id": data["bank_id"],
        "report_date": data["report_date"],
        "currency": data["currency"],
        "effective_hqla": round(total_hqla, 2),
        "net_outflows_30d": round(net_outflows, 2),
        "lcr_percent": lcr,
        "threshold": LCR_THRESHOLD,
        "status": status,
        "source_file": f"s3://{bucket}/{key}"
    }

    print(f"LCR Result: {json.dumps(result)}")

    # Store in DynamoDB
    store_result(result)

    # Publish CloudWatch metrics
    publish_metrics(result)

    # Send alert if breach
    if status == "BREACH":
        send_breach_alert(result)

    return {
        "statusCode": 200,
        "body": json.dumps(result)
    }