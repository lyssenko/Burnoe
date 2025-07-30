kill -9 $(ps aux | grep 'lora/bin/gunicorn -b 127.0.0.1:5050 csv2db_v_3:app' | awk '{print $2}')
source ~/miniconda3/bin/activate lora
nohup gunicorn -b 127.0.0.1:5050 csv2db_v_3:app &
