import json
import logging
import boto3

logger = logging.getLogger()
logger.setLevel(logging.INFO)

ecs_client = boto3.client('ecs')
rds_client = boto3.client('rds')

def lambda_handler(event, context):
    logger.info("Received event: %s", json.dumps(event))
    action = event.get('action', '').lower()
    
    cluster_name = event.get('ecs_cluster_name')
    service_names = event.get('ecs_service_names', [])
    rds_instance_ids = event.get('rds_instance_ids', [])
    
    if action == 'stop':
        # 1. Scale down ECS Fargate tasks to 0
        for svc in service_names:
            try:
                logger.info(f"Scaling down ECS service '{svc}' in cluster '{cluster_name}' to 0...")
                ecs_client.update_service(
                    cluster=cluster_name,
                    service=svc,
                    desiredCount=0
                )
                logger.info(f"Successfully set desiredCount=0 for '{svc}'")
            except Exception as e:
                logger.error(f"Error scaling down ECS service '{svc}': {str(e)}")

        # 2. Stop RDS instances
        for db_id in rds_instance_ids:
            try:
                res = rds_client.describe_db_instances(DBInstanceIdentifier=db_id)
                status = res['DBInstances'][0]['DBInstanceStatus']
                logger.info(f"RDS '{db_id}' status is '{status}'")
                if status == 'available':
                    logger.info(f"Stopping RDS DB instance '{db_id}'...")
                    rds_client.stop_db_instance(DBInstanceIdentifier=db_id)
                    logger.info(f"Successfully triggered stop for RDS DB '{db_id}'")
                else:
                    logger.info(f"Skipping RDS DB '{db_id}' stop (current status: '{status}')")
            except Exception as e:
                logger.error(f"Error stopping RDS DB '{db_id}': {str(e)}")

        return {
            "statusCode": 200,
            "body": json.dumps({"message": "Stage servers stopped successfully"})
        }

    elif action == 'start':
        # 1. Start RDS instances first
        for db_id in rds_instance_ids:
            try:
                res = rds_client.describe_db_instances(DBInstanceIdentifier=db_id)
                status = res['DBInstances'][0]['DBInstanceStatus']
                logger.info(f"RDS '{db_id}' status is '{status}'")
                if status == 'stopped':
                    logger.info(f"Starting RDS DB instance '{db_id}'...")
                    rds_client.start_db_instance(DBInstanceIdentifier=db_id)
                    logger.info(f"Successfully triggered start for RDS DB '{db_id}'")
                else:
                    logger.info(f"Skipping RDS DB '{db_id}' start (current status: '{status}')")
            except Exception as e:
                logger.error(f"Error starting RDS DB '{db_id}': {str(e)}")

        # 2. Scale up ECS Fargate tasks to 1
        for svc in service_names:
            try:
                logger.info(f"Scaling up ECS service '{svc}' in cluster '{cluster_name}' to 1...")
                ecs_client.update_service(
                    cluster=cluster_name,
                    service=svc,
                    desiredCount=1
                )
                logger.info(f"Successfully set desiredCount=1 for '{svc}'")
            except Exception as e:
                logger.error(f"Error scaling up ECS service '{svc}': {str(e)}")

        return {
            "statusCode": 200,
            "body": json.dumps({"message": "Stage servers started successfully"})
        }

    else:
        error_msg = f"Unknown or missing action: '{action}'. Expected 'stop' or 'start'."
        logger.error(error_msg)
        return {
            "statusCode": 400,
            "body": json.dumps({"error": error_msg})
        }

