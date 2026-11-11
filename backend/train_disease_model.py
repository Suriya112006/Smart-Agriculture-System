"""Train a simple image classifier from a folder-per-class dataset.

Example:
python train_disease_model.py --data-dir C:\\datasets\\plantvillage --output disease_model.keras --epochs 8

Use a dataset whose licensing and crop/disease labels fit your intended deployment.
A random image split can leak near-duplicate images; use grouped/field-separated test data
for a more reliable final evaluation.
"""
import argparse
import json
from pathlib import Path

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", required=True)
    parser.add_argument("--output", default="disease_model.keras")
    parser.add_argument("--epochs", type=int, default=8)
    parser.add_argument("--batch-size", type=int, default=32)
    args = parser.parse_args()

    import tensorflow as tf

    data_dir = Path(args.data_dir)
    if not data_dir.exists():
        raise SystemExit(f"Dataset directory not found: {data_dir}")

    train_ds = tf.keras.utils.image_dataset_from_directory(
        data_dir, validation_split=0.2, subset="training", seed=42,
        image_size=(224, 224), batch_size=args.batch_size
    )
    val_ds = tf.keras.utils.image_dataset_from_directory(
        data_dir, validation_split=0.2, subset="validation", seed=42,
        image_size=(224, 224), batch_size=args.batch_size
    )
    class_names = train_ds.class_names
    autotune = tf.data.AUTOTUNE
    train_ds = train_ds.prefetch(autotune)
    val_ds = val_ds.prefetch(autotune)

    base = tf.keras.applications.MobileNetV2(
        input_shape=(224, 224, 3), include_top=False, weights="imagenet"
    )
    base.trainable = False
    inputs = tf.keras.Input(shape=(224, 224, 3))
    x = tf.keras.applications.mobilenet_v2.preprocess_input(inputs)
    x = base(x, training=False)
    x = tf.keras.layers.GlobalAveragePooling2D()(x)
    x = tf.keras.layers.Dropout(0.25)(x)
    outputs = tf.keras.layers.Dense(len(class_names), activation="softmax")(x)
    model = tf.keras.Model(inputs, outputs)
    model.compile(optimizer="adam", loss="sparse_categorical_crossentropy", metrics=["accuracy"])
    model.fit(train_ds, validation_data=val_ds, epochs=args.epochs)
    output = Path(args.output)
    model.save(output)
    labels_path = output.with_name("disease_labels.json")
    labels_path.write_text(json.dumps(class_names, indent=2), encoding="utf-8")
    print(f"Saved model: {output.resolve()}")
    print(f"Saved labels: {labels_path.resolve()}")
    print("Review validation metrics and test on independent field images before use.")

if __name__ == "__main__":
    main()
