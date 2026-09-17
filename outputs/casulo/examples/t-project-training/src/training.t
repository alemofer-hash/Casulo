module casulo.flood_rs.training

learn FloodSurrogate
  input_features 8
  hidden_features 8
  output_features 1
  activation relu
  loss mse
  optimizer sgd
  learning_rate 0.018
  epochs 400
  precision float64
  batch full
  seed 260730
  target_loss 0.08
