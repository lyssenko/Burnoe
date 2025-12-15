kill -9 $(ps aux | grep 'lora/bin/gunicorn --timeout 120 --worker_class gthread --threads 8 -b 127.0.0.1:5050 csv2db_v_3:app' | awk '{print $2}')
source ~/miniconda3/bin/activate lora
nohup gunicorn --timeout 120 --worker-class gthread --threads 8 -b 127.0.0.1:5050 csv2db_v_3:app &
