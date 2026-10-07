# Algorithm Knowledge

## Two Sum Problem

The Two Sum problem requires finding two elements in an array whose
values add up to a specified target.

Example:

Input:

nums = [2, 7, 11, 15]
target = 9

Expected output:

[0, 1]

because:

nums[0] + nums[1] = 2 + 7 = 9

---

## Brute Force Approach

A brute force solution checks every possible pair of elements.

Typical implementation:

- Use two nested loops.
- Compare each pair.
- Return the indices when the target sum is found.

Time complexity:

O(n^2)

Space complexity:

O(1), excluding output storage.

The brute force approach is correct but may be inefficient for large
inputs.

---

## Hash Map Approach

A more efficient Two Sum solution uses a hash map to store previously
seen values and their indices.

For each element:

1. Calculate the complement:

   complement = target - current_value

2. Check whether the complement exists in the hash map.

3. If it exists, return the stored index and current index.

4. Otherwise, store the current value and its index.

Typical complexity:

Time: O(n) average case

Space: O(n)

This approach is generally preferred when the goal is efficient lookup.

---

## Algorithm Comparison

Brute Force:

- Time: O(n^2)
- Space: O(1)
- Simple implementation
- Poorer scalability

Hash Map:

- Time: O(n) average case
- Space: O(n)
- Requires additional memory
- Better scalability

A candidate using brute force should not automatically be considered
incorrect. The approach is valid, but its efficiency should be evaluated
against the requirements and available alternatives.