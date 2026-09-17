#include <math.h>
#include <stddef.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#ifdef _OPENMP
#include <omp.h>
#endif
#if defined(_WIN32)
#define CASULO_EXPORT __declspec(dllexport)
#else
#define CASULO_EXPORT __attribute__((visibility("default")))
#endif
#define INPUTS 8u
#define HIDDEN 8u
#define PARAMS (INPUTS * HIDDEN + HIDDEN + HIDDEN + 1u)

static double activate(double value) { return (value > 0.0 ? value : 0.0); }
static double derivative(double value, double hidden) {
    (void)hidden;
    return (value > 0.0 ? 1.0 : 0.0);
}
static double predict_one(const double *x, const double *p) {
    const size_t b1 = INPUTS * HIDDEN;
    const size_t w2 = b1 + HIDDEN;
    const size_t b2 = w2 + HIDDEN;
    double values[HIDDEN];
    double output = p[b2];
    size_t j, k;
    for (j = 0u; j < HIDDEN; ++j) {
        values[j] = p[b1 + j];
    }
    for (k = 0u; k < INPUTS; ++k) {
        const double input = x[k];
        for (j = 0u; j < HIDDEN; ++j) {
            values[j] += input * p[k * HIDDEN + j];
        }
    }
    for (j = 0u; j < HIDDEN; ++j) {
        output += activate(values[j]) * p[w2 + j];
    }
    return output;
}
static double evaluate_loss(
    const double *x,
    const double *y,
    size_t records,
    const double *p
) {
    double loss = 0.0;
    size_t i;
    for (i = 0u; i < records; ++i) {
        const double error = predict_one(x + i * INPUTS, p) - y[i];
        loss += error * error;
    }
    return loss / (double)records;
}
CASULO_EXPORT const char *casulo_training_artifact(void) {
    return "sha256:6bfda409e5c0c5a36400d5178902d46ef6ff610d5d3ab4acf4f742ff48dbc3a6";
}
CASULO_EXPORT size_t casulo_parameter_count(void) { return PARAMS; }
CASULO_EXPORT int casulo_train(
    const double *x,
    const double *y,
    size_t records,
    double *p,
    size_t epochs,
    double learning_rate,
    int requested_workers,
    double *initial_loss,
    double *final_loss
) {
    double *gradients;
    int workers = requested_workers;
    if (!x || !y || !p || !initial_loss || !final_loss ||
        records == 0u || epochs == 0u || learning_rate <= 0.0 ||
        workers < 1 || workers > 4) {
        return -1;
    }
#ifndef _OPENMP
    workers = 1;
#endif
    gradients = (double *)calloc((size_t)workers * (PARAMS + 1u), sizeof(double));
    if (!gradients) return -2;
    *initial_loss = evaluate_loss(x, y, records, p);
    {
        size_t epoch;
        for (epoch = 0u; epoch < epochs; ++epoch) {
            size_t q;
            memset(
                gradients,
                0,
                (size_t)workers * (PARAMS + 1u) * sizeof(double)
            );
#ifdef _OPENMP
#pragma omp parallel num_threads(workers)
#endif
            {
                int thread_id = 0;
                int team_size = 1;
                size_t start, end, i, j, k;
                double *g;
#ifdef _OPENMP
                thread_id = omp_get_thread_num();
                team_size = omp_get_num_threads();
#endif
                start = records * (size_t)thread_id / (size_t)team_size;
                end = records * (size_t)(thread_id + 1) / (size_t)team_size;
                g = gradients + (size_t)thread_id * (PARAMS + 1u);
                for (i = start; i < end; ++i) {
                    const double *row = x + i * INPUTS;
                    double hidden_values[HIDDEN];
                    double preactivation[HIDDEN];
                    double delta[HIDDEN];
                    double prediction = p[INPUTS * HIDDEN + HIDDEN + HIDDEN];
                    const double scale = 2.0 / (double)records;
                    for (j = 0u; j < HIDDEN; ++j) {
                        preactivation[j] = p[INPUTS * HIDDEN + j];
                    }
                    for (k = 0u; k < INPUTS; ++k) {
                        const double input = row[k];
                        for (j = 0u; j < HIDDEN; ++j) {
                            preactivation[j] +=
                                input * p[k * HIDDEN + j];
                        }
                    }
                    for (j = 0u; j < HIDDEN; ++j) {
                        hidden_values[j] = activate(preactivation[j]);
                        prediction += hidden_values[j] *
                            p[INPUTS * HIDDEN + HIDDEN + j];
                    }
                    {
                        const double error = prediction - y[i];
                        const double output_gradient = scale * error;
                        g[PARAMS] += error * error;
                        g[INPUTS * HIDDEN + HIDDEN + HIDDEN] += output_gradient;
                        for (j = 0u; j < HIDDEN; ++j) {
                            const double dz = output_gradient *
                                p[INPUTS * HIDDEN + HIDDEN + j] *
                                derivative(
                                    preactivation[j],
                                    hidden_values[j]
                                );
                            delta[j] = dz;
                            g[INPUTS * HIDDEN + HIDDEN + j] +=
                                output_gradient * hidden_values[j];
                            g[INPUTS * HIDDEN + j] += dz;
                        }
                        for (k = 0u; k < INPUTS; ++k) {
                            const double input = row[k];
                            for (j = 0u; j < HIDDEN; ++j) {
                                g[k * HIDDEN + j] += delta[j] * input;
                            }
                        }
                    }
                }
            }
            for (q = 0u; q < PARAMS; ++q) {
                size_t worker;
                double total = 0.0;
                for (worker = 0u; worker < (size_t)workers; ++worker) {
                    total += gradients[worker * (PARAMS + 1u) + q];
                }
                p[q] -= learning_rate * total;
            }
        }
    }
    *final_loss = evaluate_loss(x, y, records, p);
    free(gradients);
    return 0;
}
CASULO_EXPORT int casulo_predict(
    const double *x,
    size_t records,
    const double *p,
    double *predictions
) {
    size_t i;
    if (!x || !p || !predictions) return -1;
    for (i = 0u; i < records; ++i) {
        predictions[i] = predict_one(x + i * INPUTS, p);
    }
    return 0;
}
