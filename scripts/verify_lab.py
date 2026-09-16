"""Verify a temporary lab from its Terraform outputs; seed only a new synthetic item."""
import argparse
import json
import subprocess
import time
import uuid
from pathlib import Path
from urllib.parse import urlsplit

import boto3
import requests


def verify(outputs, aws, http=None, timeout=120):
    endpoint = outputs['app_api_endpoint']['value'].rstrip('/')
    host = urlsplit(endpoint)
    if (host.scheme != 'https' or not (host.hostname or '').endswith('.execute-api.us-east-1.amazonaws.com')
            or host.username or host.password or host.query or host.fragment or host.path):
        raise ValueError('Expected the us-east-1 API Gateway origin from lab Terraform outputs')
    table_name = outputs['products_table_name']['value']
    log_group = outputs['access_log_group_name']['value']
    if table_name != 'botdef-products' or log_group != '/botdef/app/access-logs':
        raise ValueError('Unexpected lab resources')
    if not 1 <= timeout <= 300:
        raise ValueError('Timeout must be between 1 and 300 seconds')
    started = int(time.time() * 1000)
    product_id = 'lab-' + uuid.uuid4().hex
    table = aws.resource('dynamodb').Table(table_name)
    table.put_item(Item={
        'product_id': product_id, 'catalog_pk': 'PRODUCT', 'title': 'Synthetic lab product',
        'price': 1, 'stock': 200, 'total_units': 200, 'drop_at': 0,
    }, ConditionExpression='attribute_not_exists(product_id)')
    http = http or requests.Session()
    http.headers.update({'User-Agent': 'botdef-lab-verification/1.0'})

    def request(method, path, expected, **kwargs):
        # Space requests below the lab throttle; never retry cart mutations.
        time.sleep(0.6)
        response = http.request(method, endpoint + path, timeout=15, allow_redirects=False, **kwargs)
        if response.status_code != expected:
            raise RuntimeError(f'{method} {path}: HTTP {response.status_code}, expected {expected}')
        return response

    request('GET', '/products', 200)
    if not any(c.name == 'session_id' and c.secure for c in http.cookies):
        raise RuntimeError('Missing secure session cookie')
    cart = request('POST', '/cart', 201, json={'product_id': product_id}).json()
    checkout = {'reservation_id': cart['reservation_id']}
    first = request('POST', '/checkout', 200, json=checkout).json()
    second = request('POST', '/checkout', 200, json=checkout).json()
    if not first.get('order_id') or first['order_id'] != second.get('order_id'):
        raise RuntimeError('Checkout retry did not return the same order')
    probe = request('GET', '/products/missing-' + uuid.uuid4().hex, 404)
    request_id = probe.headers.get('apigw-requestid') or probe.headers.get('x-amzn-requestid')
    if not request_id:
        raise RuntimeError('Missing API request ID')
    logs = aws.client('logs')
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        matches = logs.filter_log_events(logGroupName=log_group, startTime=started,
                                        filterPattern=json.dumps(request_id), limit=20)
        if matches.get('events'):
            return {'status': 'passed', 'synthetic': False, 'product_id': product_id,
                    'request_id': request_id,
                    'checks': {'secure_cookie': True, 'checkout_retry': True, 'cloudwatch_access_log': True},
                    'limitations': ['No WAF deployed', 'ML evaluation is offline', 'Synthetic shoppers and inventory']}
        time.sleep(min(5, max(0, deadline - time.monotonic())))
    raise TimeoutError('CloudWatch did not deliver the correlated API access log in time')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--profile', default='botdef')
    parser.add_argument('--acknowledge-owned-target', action='store_true', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    try:
        result = subprocess.run(['terraform', '-chdir=' + str(root / 'infra/envs/lab'), 'output', '-json'],
                                check=True, capture_output=True, text=True)
        # Export to memory for compatibility with SDKs predating aws login support.
        credentials = json.loads(subprocess.run(
            ['aws', 'configure', 'export-credentials', '--profile', args.profile, '--region', 'us-east-1', '--format', 'process'],
            check=True, capture_output=True, text=True).stdout)
        aws = boto3.Session(aws_access_key_id=credentials['AccessKeyId'],
                            aws_secret_access_key=credentials['SecretAccessKey'],
                            aws_session_token=credentials['SessionToken'], region_name='us-east-1')
        report = verify(json.loads(result.stdout), aws)
    except Exception as error:
        report = {'status': 'failed', 'error_type': type(error).__name__}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(report))
    return 0 if report['status'] == 'passed' else 1


if __name__ == '__main__':
    raise SystemExit(main())
