# IT-16 — Rejilla de estrategias de fragmentación

Generado el 05/08/2026 con `py -u scripts/experimento_fragmentacion.py` sobre `data/grados.json`, con 50 preguntas de `eval/preguntas_evaluacion.json` y el modelo `intfloat/multilingual-e5-small` (ventana de 512 tokens), en CPU.

**45 configuraciones.** Las tres estrategias comparten el eje de tamaño máximo y tienen el mismo número de variantes de su parámetro propio, de modo que ninguna compite con más intentos que otra.

| Estrategia | Máx. | Ajuste | Frag. | Mediana | RU@1 | RU@3 | RU@5 | RU@10 | RU@15 | R@5 / techo | MRR | Trunc. |
|---|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| fijo | 600 | solape 0% | 2312 | 600 | 0.950 | 0.985 | 0.985 | 1.000 | 1.000 | 0.714 / 0.805 | 0.972 | 0 |
| fijo | 900 | solape 20% | 1477 | 900 | 0.935 | 0.965 | 0.990 | 1.000 | 1.000 | 0.778 / 0.890 | 0.974 | 0 |
| estructural | 900 | objetivo 100% | 1334 | 838 | 0.930 | 0.985 | 0.990 | 1.000 | 1.000 | 0.803 / 0.906 | 0.970 | 0 |
| estructural | 600 | objetivo 80% | 3054 | 479 | 0.930 | 0.980 | 0.985 | 1.000 | 1.000 | 0.656 / 0.745 | 0.965 | 0 |
| semantica | 600 | percentil 30 | 2931 | 546 | 0.930 | 0.980 | 0.985 | 1.000 | 1.000 | 0.651 / 0.751 | 0.965 | 0 |
| semantica | 600 | percentil 50 | 2951 | 544 | 0.930 | 0.980 | 0.985 | 1.000 | 1.000 | 0.651 / 0.752 | 0.965 | 0 |
| estructural | 600 | objetivo 60% | 3040 | 525 | 0.930 | 0.980 | 0.985 | 1.000 | 1.000 | 0.633 / 0.716 | 0.964 | 0 |
| semantica | 600 | percentil 70 | 2949 | 546 | 0.930 | 0.980 | 0.985 | 1.000 | 1.000 | 0.645 / 0.748 | 0.964 | 0 |
| semantica | 900 | percentil 70 | 1647 | 673 | 0.930 | 0.985 | 0.985 | 1.000 | 1.000 | 0.776 / 0.870 | 0.963 | 0 |
| fijo | 900 | solape 0% | 1228 | 900 | 0.930 | 0.985 | 0.990 | 1.000 | 1.000 | 0.811 / 0.917 | 0.963 | 0 |
| semantica | 900 | percentil 30 | 1614 | 671 | 0.930 | 0.980 | 0.985 | 1.000 | 1.000 | 0.762 / 0.856 | 0.961 | 0 |
| estructural | 600 | objetivo 100% | 2695 | 569 | 0.930 | 0.980 | 0.985 | 1.000 | 1.000 | 0.687 / 0.778 | 0.960 | 0 |
| estructural | 900 | objetivo 60% | 1949 | 526 | 0.930 | 0.980 | 0.985 | 1.000 | 1.000 | 0.722 / 0.825 | 0.960 | 0 |
| estructural | 900 | objetivo 80% | 1612 | 691 | 0.930 | 0.985 | 0.985 | 1.000 | 1.000 | 0.784 / 0.874 | 0.960 | 0 |
| fijo | 600 | solape 10% | 2545 | 600 | 0.930 | 0.985 | 0.990 | 1.000 | 1.000 | 0.687 / 0.786 | 0.958 | 0 |
| fijo | 1200 | solape 0% | 912 | 1199 | 0.910 | 0.985 | 0.990 | 0.995 | 0.995 | 0.804 / 0.956 | 0.960 | 0 |
| fijo | 1800 | solape 20% | 740 | 1745 | 0.910 | 0.960 | 0.970 | 0.995 | 0.995 | 0.860 / 0.980 | 0.953 | 29 |
| fijo | 600 | solape 20% | 2835 | 600 | 0.910 | 0.980 | 0.990 | 1.000 | 1.000 | 0.664 / 0.756 | 0.952 | 0 |
| semantica | 900 | percentil 50 | 1662 | 653 | 0.910 | 0.980 | 0.985 | 1.000 | 1.000 | 0.768 / 0.864 | 0.951 | 0 |
| semantica | 1200 | percentil 30 | 1263 | 738 | 0.890 | 0.980 | 0.990 | 1.000 | 1.000 | 0.794 / 0.897 | 0.942 | 0 |
| estructural | 1200 | objetivo 60% | 1499 | 695 | 0.890 | 0.985 | 0.990 | 1.000 | 1.000 | 0.792 / 0.883 | 0.940 | 0 |
| fijo | 1200 | solape 20% | 1070 | 1199 | 0.890 | 0.965 | 0.990 | 0.995 | 0.995 | 0.794 / 0.935 | 0.939 | 0 |
| semantica | 1200 | percentil 70 | 1311 | 724 | 0.890 | 0.985 | 0.990 | 1.000 | 1.000 | 0.797 / 0.905 | 0.938 | 0 |
| fijo | 900 | solape 10% | 1330 | 900 | 0.890 | 0.960 | 0.990 | 1.000 | 1.000 | 0.787 / 0.911 | 0.937 | 0 |
| semantica | 1200 | percentil 50 | 1324 | 714 | 0.870 | 0.980 | 0.990 | 1.000 | 1.000 | 0.796 / 0.905 | 0.932 | 0 |
| fijo | 1500 | solape 20% | 878 | 1499 | 0.870 | 0.925 | 0.990 | 0.995 | 0.995 | 0.811 / 0.962 | 0.920 | 3 |
| estructural | 1500 | objetivo 60% | 1149 | 864 | 0.850 | 0.985 | 0.990 | 1.000 | 1.000 | 0.839 / 0.930 | 0.927 | 0 |
| fijo | 1500 | solape 0% | 736 | 1499 | 0.850 | 0.985 | 0.990 | 0.995 | 0.995 | 0.853 / 0.979 | 0.927 | 3 |
| estructural | 1200 | objetivo 80% | 1140 | 910 | 0.850 | 0.990 | 0.995 | 1.000 | 1.000 | 0.813 / 0.920 | 0.925 | 0 |
| fijo | 1200 | solape 10% | 979 | 1200 | 0.850 | 0.965 | 0.990 | 0.995 | 0.995 | 0.802 / 0.946 | 0.920 | 0 |
| estructural | 1200 | objetivo 100% | 947 | 1104 | 0.850 | 0.960 | 0.990 | 0.995 | 0.995 | 0.820 / 0.953 | 0.913 | 0 |
| semantica | 1500 | percentil 30 | 1046 | 837 | 0.850 | 0.965 | 0.990 | 1.000 | 1.000 | 0.811 / 0.929 | 0.913 | 4 |
| fijo | 1500 | solape 10% | 790 | 1499 | 0.850 | 0.925 | 0.975 | 1.000 | 1.000 | 0.847 / 0.974 | 0.908 | 3 |
| fijo | 1800 | solape 10% | 673 | 1711 | 0.830 | 0.950 | 0.990 | 0.995 | 0.995 | 0.854 / 0.987 | 0.902 | 29 |
| semantica | 1500 | percentil 50 | 1119 | 774 | 0.830 | 0.965 | 0.990 | 1.000 | 1.000 | 0.833 / 0.941 | 0.901 | 4 |
| semantica | 1800 | percentil 70 | 1048 | 794 | 0.830 | 0.945 | 0.990 | 0.995 | 0.995 | 0.813 / 0.945 | 0.901 | 7 |
| semantica | 1800 | percentil 50 | 1018 | 810 | 0.830 | 0.945 | 0.990 | 0.995 | 0.995 | 0.830 / 0.955 | 0.900 | 7 |
| estructural | 1500 | objetivo 100% | 753 | 1344 | 0.830 | 0.945 | 0.990 | 0.995 | 0.995 | 0.831 / 0.976 | 0.898 | 4 |
| semantica | 1500 | percentil 70 | 1139 | 764 | 0.830 | 0.945 | 0.990 | 1.000 | 1.000 | 0.824 / 0.940 | 0.898 | 4 |
| estructural | 1800 | objetivo 60% | 940 | 1037 | 0.820 | 0.965 | 0.990 | 0.995 | 0.995 | 0.831 / 0.945 | 0.893 | 0 |
| semantica | 1800 | percentil 30 | 942 | 872 | 0.810 | 0.985 | 0.990 | 0.995 | 0.995 | 0.833 / 0.945 | 0.907 | 8 |
| fijo | 1800 | solape 0% | 623 | 1728 | 0.790 | 0.945 | 0.970 | 0.995 | 0.995 | 0.866 / 0.989 | 0.885 | 20 |
| estructural | 1800 | objetivo 80% | 751 | 1334 | 0.790 | 0.965 | 0.990 | 0.995 | 0.995 | 0.853 / 0.977 | 0.882 | 1 |
| estructural | 1500 | objetivo 80% | 884 | 1139 | 0.780 | 0.965 | 0.990 | 0.995 | 0.995 | 0.849 / 0.963 | 0.875 | 0 |
| estructural | 1800 | objetivo 100% | 632 | 1497 | 0.770 | 0.945 | 0.970 | 0.995 | 0.995 | 0.869 / 0.989 | 0.868 | 11 |

Ordenada por exhaustividad por unidad en el primer resultado, que es donde las configuraciones se distinguen: a partir de K=5 se saturan y empatan casi todas.

## Cómo leer la tabla

- **RU@K** es la exhaustividad por unidad: si se ha encontrado la asignatura correcta. Es la métrica principal porque el conjunto de evaluación anota unidades y no fragmentos. Aun así **no es inmune al troceo**: una unidad partida en más fragmentos ocupa más huecos del top-K, así que la columna **Frag.** hay que leerla al lado.
- **R@5 / techo** es la exhaustividad por fragmento con su máximo alcanzable. Al cambiar el troceo cambian el denominador de esa métrica y su techo, de modo que la cifra suelta no es comparable entre configuraciones.
- **Trunc.** son los fragmentos que superan la ventana del modelo y que `encode` recorta **en silencio**, sin avisar ni fallar. Es la comprobación directa de por qué el máximo de fragmento no puede subirse sin mirar.
