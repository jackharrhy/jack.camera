export function toFraction(x: number, tolerance: number = 0.0001) {
  if (x === 0) return [0, 1];
  if (x < 0) x = -x;

  let num = 1;
  let den = 1;

  const iterate = () => {
    const R = num / den;
    if (Math.abs((R - x) / x) < tolerance) return;

    if (R < x) {
      num++;
    } else {
      den++;
    }

    iterate();
  };

  iterate();
  return `${num}/${den}`;
}
