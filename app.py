from flask import Flask, render_template, request, jsonify, session, redirect, url_for
import mysql.connector
import os
from datetime import datetime
template_dir = os.path.abspath('../templates')
app = Flask(__name__, template_folder=template_dir)
app.secret_key = 'your_secret_key_here'
try:
    db = mysql.connector.connect(
        host="localhost",
        user="root",
        password="tiger",
        database="DBMSPROJ"
    )
    cursor = db.cursor(dictionary=True)
    print("Database connected successfully!")
except mysql.connector.Error as err:
    print(f"Database connection error: {err}")
    db = None
    cursor = None

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/login', methods=['POST'])
def login():
    try:
        data = request.get_json()
        if not data:
            return jsonify({'success': False, 'message': 'No data received'})
            
        login_type = data.get('type')
        username = data.get('username')
        password = data.get('password')

        print(f"Login attempt - Type: {login_type}, Username: {username}")

        if not all([login_type, username, password]):
            return jsonify({'success': False, 'message': 'All fields are required'})

        if db is None or cursor is None:
            return jsonify({'success': False, 'message': 'Database connection error'})

        if login_type == 'customer':
            cursor.execute("SELECT * FROM customer WHERE customer_email=%s AND customer_password=%s", (username, password))
        elif login_type == 'admin':
            cursor.execute("SELECT * FROM admin WHERE admin_name=%s AND admin_password=%s", (username, password))
        else:
            return jsonify({'success': False, 'message': 'Invalid login type'})

        user = cursor.fetchone()

        if user:
            session['user_id'] = user['customer_id'] if login_type == 'customer' else user['admin_id']
            session['user_type'] = login_type
            session['username'] = username
            
            redirect_url = '/admin_dashboard' if login_type == 'admin' else '/home'
            return jsonify({
                'success': True,
                'message': f'{login_type.capitalize()} login successful!',
                'redirect': redirect_url
            })
        else:
            return jsonify({'success': False, 'message': 'Invalid username or password'})
            
    except Exception as e:
        print(f"Login error: {str(e)}")
        return jsonify({'success': False, 'message': f'Server error: {str(e)}'})

@app.route('/home')
def home():
    restaurants = []
    try:
        if db and cursor:
            cursor.execute("SELECT * FROM restaurant")
            restaurants = cursor.fetchall()
            print(f"Found {len(restaurants)} restaurants")
    except Exception as e:
        print(f"Error fetching restaurants: {e}")
    
    return render_template('customer.html', restaurants=restaurants)

@app.route('/get_restaurants')
def get_restaurants():
    try:
        if db and cursor:
            cursor.execute("SELECT * FROM restaurant")
            restaurants = cursor.fetchall()
            return jsonify({'success': True, 'restaurants': restaurants})
        else:
            return jsonify({'success': False, 'message': 'Database connection error'})
    except Exception as e:
        print(f"Error fetching restaurants: {e}")
        return jsonify({'success': False, 'message': 'Error fetching restaurants'})

@app.route('/menu/<int:restaurant_id>')
def menu(restaurant_id):
    try:
        if db and cursor:
            cursor.execute("SELECT * FROM restaurant WHERE restaurant_id = %s", (restaurant_id,))
            restaurant = cursor.fetchone()
            cursor.execute("SELECT * FROM menu_item WHERE restaurant_id = %s", (restaurant_id,))
            menu_items = cursor.fetchall()

            if restaurant:
                return render_template(f'menu_{restaurant_id}.html', 
                                    restaurant=restaurant, 
                                    menu_items=menu_items)
            else:
                return "Restaurant not found", 404
        else:
            return "Database connection error", 500
    except Exception as e:
        print(f"Error loading menu: {e}")
        return "Error loading menu", 500

@app.route('/checkout', methods=['POST'])
def checkout():
    try:
        if db is None or cursor is None:
            return jsonify({'success': False, 'message': 'Database connection error'})

        data = request.get_json()
        cart_items = data.get('cart', [])
        total_amount = data.get('total', 0)
        delivery_address = data.get('delivery_address', '')
        payment_mode = data.get('payment_mode', 'Cash')

        if not cart_items:
            return jsonify({'success': False, 'message': 'Cart is empty'})
        
        customer_id = session.get('user_id')
        if not customer_id:
            return jsonify({'success': False, 'message': 'Please login first'})

        print(f"Checkout for customer {customer_id}")
        
        try:
            if db.in_transaction:
                db.rollback()
        except:
            pass

        db.start_transaction()

        try:

            cursor.execute(
                "INSERT INTO delivery_details (delivery_status, delivery_address) VALUES (%s, %s)", 
                ('Pending', delivery_address)
            )
            delivery_id = cursor.lastrowid

            cursor.execute(
                "INSERT INTO payment_details (payment_mode) VALUES (%s)", 
                (payment_mode,)
            )
            payment_id = cursor.lastrowid

            # Create order details
            cursor.execute("""
                INSERT INTO order_details (order_amount, order_status, customers_id, delivery_id, payment_id)
                VALUES (%s, %s, %s, %s, %s)
            """, (total_amount, 'Confirmed', customer_id, delivery_id, payment_id))
            order_id = cursor.lastrowid

            # Insert order items
            for item in cart_items:
                cursor.execute(
                    "INSERT INTO order_items (order_id, item_id, quantity, price) VALUES (%s, %s, %s, %s)",
                    (order_id, item['id'], item['quantity'], item['price'])
                )

            db.commit()
            print(f"Order {order_id} successfully placed!")

            return jsonify({
                'success': True,
                'message': 'Order placed successfully!',
                'order_id': order_id,
                'total_amount': total_amount,
                'redirect': f'/bill/{order_id}'
            })

        except mysql.connector.Error as e:
            db.rollback()
            print(f"Database error during checkout: {e}")
            return jsonify({'success': False, 'message': f'Database error: {str(e)}'})
        except Exception as e:
            db.rollback()
            print(f"Checkout transaction error: {e}")
            return jsonify({'success': False, 'message': f'Checkout failed: {str(e)}'})

    except Exception as e:
        print(f"Checkout error: {e}")
        return jsonify({'success': False, 'message': f'Server error during checkout: {str(e)}'})

@app.route('/bill/<int:order_id>')
def generate_bill(order_id):
    try:
        if db and cursor:
            cursor.execute("""
                SELECT 
                    od.order_id, od.order_timestamp, od.order_amount, od.order_status,
                    c.customer_id, c.customer_email, 
                    COALESCE(c.customer_name, c.customer_email) as customer_name,
                    dd.delivery_address, dd.delivery_status,
                    pd.payment_mode, pd.payment_timestamp
                FROM order_details od
                JOIN customer c ON od.customers_id = c.customer_id
                JOIN delivery_details dd ON od.delivery_id = dd.delivery_id
                JOIN payment_details pd ON od.payment_id = pd.payment_id
                WHERE od.order_id = %s
            """, (order_id,))
            order = cursor.fetchone()

            if not order:
                return "Order not found", 404
            try:
                cursor.execute("""
                    SELECT oi.item_id, oi.quantity, oi.price, 
                           COALESCE(mi.item_name, CONCAT('Item ', oi.item_id)) as item_name
                    FROM order_items oi
                    LEFT JOIN menu_item mi ON oi.item_id = mi.item_id
                    WHERE oi.order_id = %s
                """, (order_id,))
                items = cursor.fetchall()
            except mysql.connector.Error as e:
                cursor.execute("SELECT item_id, quantity, price FROM order_items WHERE order_id = %s", (order_id,))
                items = cursor.fetchall()
                for item in items:
                    item['item_name'] = f"Item {item['item_id']}"

            return render_template('bill.html', order=order, items=items)
        else:
            return "Database connection error", 500
    except Exception as e:
        print(f"Bill generation error: {e}")
        return f"Error generating bill: {str(e)}", 500

@app.route('/admin_dashboard')
def admin_dashboard():
    return """
    <!DOCTYPE html>
    <html>
    <head>
        <title>FoodHub - Admin Dashboard</title>
        <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.1.3/dist/css/bootstrap.min.css" rel="stylesheet">
    </head>
    <body>
        <div class="container mt-5">
            <h1>Admin Dashboard</h1>
            <p>You have successfully logged in as an administrator.</p>
            <a href="/" class="btn btn-primary">Back to Login</a>
            <a href="/orders" class="btn btn-info">View Orders (API)</a>
        </div>
    </body>
    </html>
    """

@app.route('/orders')
def view_orders():
    try:
        if db and cursor:
            cursor.execute("""
                SELECT od.order_id, od.order_timestamp, od.order_amount, od.order_status,
                       c.customer_email, dd.delivery_address, dd.delivery_status, pd.payment_mode
                FROM order_details od
                JOIN customer c ON od.customers_id = c.customer_id
                JOIN delivery_details dd ON od.delivery_id = dd.delivery_id
                JOIN payment_details pd ON od.payment_id = pd.payment_id
                ORDER BY od.order_timestamp DESC
            """)
            orders = cursor.fetchall()
            
            cursor.execute("SELECT * FROM order_items oi JOIN menu_item mi ON oi.item_id = mi.item_id")
            order_items = cursor.fetchall()
            
            return jsonify({'success': True, 'orders': orders, 'order_items': order_items})
        else:
            return jsonify({'success': False, 'message': 'Database connection error'})
    except Exception as e:
        print(f"Error fetching orders: {e}")
        return jsonify({'success': False, 'message': f'Error fetching orders: {str(e)}'})

@app.errorhandler(404)
def not_found(e):
    return jsonify({'error': 'Endpoint not found'}), 404

@app.errorhandler(500)
def server_error(e):
    return jsonify({'error': 'Internal server error'}), 500

if __name__ == '__main__':
    print("Starting Flask server...")
    print(f"Template folder: {app.template_folder}")
    app.run(debug=True, host='127.0.0.1', port=5000)
