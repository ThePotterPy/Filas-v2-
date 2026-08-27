# gestor de filas expy fest

esta app es para manejar las filas y la logistica del evento en tiempo real. 

## funcioanmiento

- manejo de expereiencias: podes crear editar y borrar las atracciones y ponerle un tiempo a cada una.
- filas y espera: vas agregando gente a la fila y la app saca sola el calculo de cuanto van a esperar mas o menos.
- panel en vivo: todo se actualiza solo sin tener q recargar la pagina.
- voluntarixs: podes anotar al staff y asignarles un puesto o ponerlos en descanso
- alertas: hay un boton de sos por si pasa algo y otro para hacer anuncios a la pantalla principal como cuando se libera un puesto.
- base de datos: usa sqlite aca en la compu pero cuando lo subis se cambia a postgres solo

## para subir a railway

tenes q tener en cuenta un par de cosas para q ande bien cuando lo subas a railway.

- variables: tenes q crear una variable q se llame SECRET_KEY y ponerle calquier cosa rara. el PORT no hace falta porq railway te lo pone solo.
- base de datos postgres: como railway te borra los archivos cada vez q se apaga no podes usar sqlite. tenes q ir a new database y agegar postgres. una vez q se crea le copias la variable DATABASE_URL y se la pegas a las variables de tu app. ahi el codigo ya se da cuenta y arma todo solo.
- archivos: no borres el requirements.txt ni el Procfile porq si no railway no va a saber como prender la pagina.
- reinicios: cada vez q subas un cambio la pagian se reinicia pero tranqui q como usamos postgrees no se pierde nada de la fila.
