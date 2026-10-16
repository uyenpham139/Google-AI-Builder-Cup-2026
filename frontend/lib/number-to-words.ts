/**
 * Converts numeric amount to English words (e.g., 2,450,000 -> "Two million four hundred fifty thousand dollars")
 */
export function numberToEnglishWords(n: number): string {
  if (isNaN(n) || n === 0) return 'Zero dollars';
  if (n < 0) return 'Negative ' + numberToEnglishWords(Math.abs(n));

  const ones = [
    '', 'one', 'two', 'three', 'four', 'five', 'six', 'seven', 'eight', 'nine',
    'ten', 'eleven', 'twelve', 'thirteen', 'fourteen', 'fifteen', 'sixteen',
    'seventeen', 'eighteen', 'nineteen'
  ];
  const tens = ['', '', 'twenty', 'thirty', 'forty', 'fifty', 'sixty', 'seventy', 'eighty', 'ninety'];
  const thousands = ['', 'thousand', 'million', 'billion', 'trillion'];

  function helper(num: number): string {
    if (num === 0) return '';
    if (num < 20) return ones[num] + ' ';
    if (num < 100) return tens[Math.floor(num / 10)] + (num % 10 !== 0 ? '-' + ones[num % 10] : '') + ' ';
    return ones[Math.floor(num / 100)] + ' hundred ' + helper(num % 100);
  }

  let words = '';
  let i = 0;
  let temp = Math.floor(n);
  while (temp > 0) {
    if (temp % 1000 !== 0) {
      words = helper(temp % 1000) + thousands[i] + ' ' + words;
    }
    temp = Math.floor(temp / 1000);
    i++;
  }
  const result = words.trim();
  return result.charAt(0).toUpperCase() + result.slice(1) + ' dollars';
}

// Backward-compatibility alias
export const numberToVietnameseWords = numberToEnglishWords;
