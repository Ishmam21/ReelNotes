# PostgreSQL data integrity

Apply these instructions when implementing seat bookings across events.

## Booking uniqueness

- Enforce uniqueness on the event and seat together. Apply this constraint when a seat can be sold for different events.
