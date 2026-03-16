# LiquidEye — Liquidity Risk Monitor

A serverless AWS system that monitors a bank's **Liquidity Coverage Ratio (LCR)** in real time, applying Basel III regulatory calculations and alerting risk teams when thresholds are breached.

## What it does

When a treasury system drops a daily cash flow position file into S3, LiquidEye automatically:

1. **Parses** the position data (HQLA levels, cash outflows, cash inflows)
2. **Calculates** the Basel III LCR with proper haircuts (Level 1: 0%, Level 2A: 15%, Level 2B: 50%) and the 75% inflow cap
3. **Stores** the timestamped result in DynamoDB for historical tracking
4. **Publishes** custom CloudWatch metrics for dashboard visualisation
5. **Alerts** via email (SNS) if the LCR drops below the 100% regulatory threshold

## Architecture

```
Treasury System → S3 Bucket → Lambda (LCR Calculation)
                                  ├── DynamoDB (Result History)
                                  ├── CloudWatch (Dashboard Metrics)
                                  └── SNS → Email (Breach Alerts)
```

**Services used:** S3, Lambda (Python 3.12), DynamoDB, SNS, CloudWatch

## The LCR Formula

```
LCR = Effective HQLA / Net Cash Outflows (30-day horizon) × 100
```

Where:
- **Effective HQLA** = Level 1 assets (100%) + Level 2A assets (85%) + Level 2B assets (50%)
- **Net Cash Outflows** = Total Outflows − min(Total Inflows, 75% × Total Outflows)
- **Regulatory minimum**: LCR must be ≥ 100% under Basel III

## Data Schema

Each position file is a JSON document representing a single day's liquidity snapshot:

```json
{
  "bank_id": "BANK_001",
  "report_date": "2026-03-14",
  "currency": "GBP",
  "hqla": {
    "level_1": 250000000,
    "level_2a": 60000000,
    "level_2b": 15000000
  },
  "cash_outflows_30d": {
    "retail_deposits": 95000000,
    "unsecured_wholesale": 230000000,
    "secured_funding": 70000000,
    "other_outflows": 55000000
  },
  "cash_inflows_30d": {
    "secured_lending": 45000000,
    "retail_inflows": 20000000,
    "other_inflows": 12000000
  }
}
```

## Sample Data

The `sample-data/` directory contains 6 daily position files simulating a liquidity stress event:

| Date | Effective HQLA | Net Outflows | LCR | Status |
|------|---------------|-------------|-----|--------|
| 2026-03-11 | £617M | £260M | 237.3% | Healthy |
| 2026-03-12 | £578M | £274M | 210.8% | Healthy |
| 2026-03-13 | £398M | £320M | 124.4% | Healthy |
| 2026-03-14 | £309M | £373M | 82.7% | **BREACH** |
| 2026-03-15 | £239M | £425M | 56.2% | **BREACH** |
| 2026-03-16 | £558M | £264M | 211.2% | Recovery |

## Breach Alert Example

When LCR drops below 100%, the risk team receives an email like this:

```
=====================================
  LIQUIDITY COVERAGE RATIO BREACH
=====================================

Bank:            BANK_001
Report Date:     2026-03-14
Currency:        GBP

LCR:             82.71%
Threshold:       100.0%
Shortfall:       17.29 percentage points

Effective HQLA:  GBP 308,500,000.00
Net Outflows:    GBP 373,000,000.00

ACTION REQUIRED: Immediate review by Treasury/Risk team.
=====================================
```

## Setup

### Prerequisites
- AWS account with free tier access
- AWS CLI configured (optional, for deployment)

### Deployment (Console)

1. **S3**: Create bucket `liquideye-cashflow-positions` in your preferred region
2. **DynamoDB**: Create table `liquideye-lcr-results` with partition key `bank_id` (String) and sort key `report_date` (String)
3. **SNS**: Create topic `liquideye-lcr-alerts`, subscribe your email, confirm the subscription
4. **Lambda**: Create function `liquideye-lcr-calculator` (Python 3.12), paste `lambda_function.py`, update the `SNS_TOPIC_ARN` variable
5. **IAM**: Attach `AmazonS3ReadOnlyAccess`, `AmazonDynamoDBFullAccess`, `AmazonSNSFullAccess`, and `CloudWatchFullAccess` to the Lambda execution role
6. **S3 Trigger**: Add an S3 event notification on the bucket for "All object create events" with `.json` suffix, pointing to the Lambda
7. **CloudWatch**: Create dashboard `LiquidEye-LCR-Monitor` with LCR_Percent line graph and Basel III threshold annotation at 100%

### Test

Upload any of the sample JSON files to the S3 bucket. Check:
- CloudWatch Logs for the Lambda execution and LCR result
- DynamoDB table for the stored result
- Your email for breach alerts (files with LCR < 100%)

## Future Enhancements

- **Net Stable Funding Ratio (NSFR)** as a second Basel III metric
- **Granular run-off rates** on outflow categories (retail: 5-10%, wholesale: 25-100%)
- **API Gateway** endpoint for real-time position queries from the DynamoDB table
- **CloudWatch Alarms** with automatic escalation (e.g. PagerDuty integration)
- **Multi-bank support** leveraging the DynamoDB partition key design
- **Terraform/IaC** deployment for reproducible infrastructure

## Tech Stack

- **Compute**: AWS Lambda (Python 3.12)
- **Storage**: Amazon S3, Amazon DynamoDB
- **Messaging**: Amazon SNS
- **Monitoring**: Amazon CloudWatch (custom metrics + dashboard)
- **Security**: IAM least-privilege roles

## License

MIT