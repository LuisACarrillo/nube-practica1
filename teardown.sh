#!/bin/bash
set -euo pipefail
export AWS_DEFAULT_REGION=us-east-1

DB_ID=instabox-db
BUCKET=instabox-824471256666

echo "Buscando la instancia instabox-api..."
INSTANCE_ID=$(aws ec2 describe-instances \
  --filters Name=tag:Name,Values=instabox-api Name=instance-state-name,Values=pending,running,stopping,stopped \
  --query "Reservations[].Instances[].InstanceId" \
  --output text)

if [ -n "$INSTANCE_ID" ] && [ "$INSTANCE_ID" != "None" ]; then
  echo "Terminando $INSTANCE_ID"
  aws ec2 terminate-instances --instance-ids $INSTANCE_ID >/dev/null
else
  echo "No hay instancia instabox-api activa"
  INSTANCE_ID=""
fi

SECRET=""
DB_DELETING=0
if aws rds describe-db-instances --db-instance-identifier "$DB_ID" >/dev/null 2>&1; then
  SECRET=$(aws rds describe-db-instances --db-instance-identifier "$DB_ID" \
    --query "DBInstances[0].MasterUserSecret.SecretArn" --output text)
  echo "Borrando la base $DB_ID"
  aws rds delete-db-instance \
    --db-instance-identifier "$DB_ID" \
    --skip-final-snapshot \
    --delete-automated-backups >/dev/null
  DB_DELETING=1
else
  echo "No existe la base $DB_ID"
fi

if aws s3api head-bucket --bucket "$BUCKET" >/dev/null 2>&1; then
  echo "Vaciando y borrando el bucket $BUCKET"
  aws s3 rm "s3://$BUCKET" --recursive
  aws s3 rb "s3://$BUCKET"
else
  echo "No existe el bucket $BUCKET"
fi

if [ -n "$INSTANCE_ID" ]; then
  echo "Esperando a que la instancia termine..."
  aws ec2 wait instance-terminated --instance-ids $INSTANCE_ID
fi

if [ "$DB_DELETING" = 1 ]; then
  echo "Esperando a que la base se borre..."
  aws rds wait db-instance-deleted --db-instance-identifier "$DB_ID"
fi

if [ -n "$SECRET" ] && [ "$SECRET" != "None" ]; then
  echo "Borrando el secreto"
  aws secretsmanager delete-secret --secret-id "$SECRET" --force-delete-without-recovery >/dev/null \
    || echo "El secreto ya lo eliminó RDS"
fi

delete_sg() {
  local name="$1"
  local id
  local i
  id=$(aws ec2 describe-security-groups --filters "Name=group-name,Values=$name" \
    --query "SecurityGroups[0].GroupId" --output text)
  if [ -z "$id" ] || [ "$id" = "None" ]; then
    echo "No existe el security group $name"
    return 0
  fi
  echo "Borrando $name ($id)"
  for i in 1 2 3 4 5 6 7 8; do
    if aws ec2 delete-security-group --group-id "$id" >/dev/null 2>&1; then
      return 0
    fi
    echo "Sigue en uso, reintento $i..."
    sleep 15
  done
  echo "No se pudo borrar $name"
  return 1
}

delete_sg instabox-db-sg
delete_sg instabox-api-sg

echo "InstaBox eliminado."
echo "Siguen la VPC por defecto, la llave vockey, LabInstanceProfile y el bucket logging."
